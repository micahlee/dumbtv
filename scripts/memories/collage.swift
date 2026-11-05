// Native, offline collage rendering and content fingerprints. Originals are read-only.
import Foundation
import ImageIO
import CoreGraphics
import CoreImage
import CoreText
import CryptoKit
import Vision

func fail() -> Never { fputs("collage preparation failed\n", stderr); exit(1) }
func thumbnail(_ path: String, maximum: Int, mode: String = "metadata") -> CGImage {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: mode != "pixels",
            kCGImageSourceThumbnailMaxPixelSize: maximum,
            kCGImageSourceShouldCacheImmediately: true
          ] as CFDictionary) else { fail() }
    return image
}
func raster(_ image: CGImage, width: Int, height: Int) -> [UInt8] {
    var bytes = [UInt8](repeating: 0, count: width * height * 4)
    bytes.withUnsafeMutableBytes { storage in
        guard let color = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: storage.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: color,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { fail() }
        context.setFillColor(CGColor(gray: 0, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    }
    return bytes
}
func printJSON(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value),
          let text = String(data: data, encoding: .utf8) else { fail() }
    print(text)
}
func poses(_ image: CGImage) -> [FacePose] {
    let request = VNDetectFaceRectanglesRequest()
    guard (try? VNImageRequestHandler(cgImage: image).perform([request])) != nil else { return [] }
    return (request.results ?? []).map {
        FacePose(confidence: Double($0.confidence), area: Double($0.boundingBox.width*$0.boundingBox.height),
                 roll: $0.roll?.doubleValue)
    }
}
func properties(_ path: String) -> NSDictionary {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) else { fail() }
    return props as NSDictionary
}
func text(_ string: String, font: String, size: CGFloat, color: CGColor, at point: CGPoint,
          width: CGFloat, canvas: CGContext) {
    var actual = size
    func line(_ size: CGFloat) -> CTLine {
        return CTLineCreateWithAttributedString(NSAttributedString(string: string, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): CTFontCreateWithName(font as CFString, size, nil),
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): color]))
    }
    var value = line(actual)
    while CTLineGetTypographicBounds(value, nil, nil, nil) > Double(width) && actual > 18 {
        actual -= 1; value = line(actual)
    }
    // Never let unexpected metadata paint outside the print's caption band.
    canvas.saveGState(); canvas.clip(to: CGRect(x:point.x, y:point.y-10, width:width, height:size+24))
    canvas.textMatrix = .identity; canvas.textPosition = point; CTLineDraw(value, canvas); canvas.restoreGState()
}
let args = CommandLine.arguments
if [3, 4].contains(args.count) && args[1] == "--fingerprint" {
    let reviewed = args.count == 4 ? args[3] : "automatic"
    guard ["automatic", "metadata", "pixels"].contains(reviewed) else { fail() }
    let props = properties(args[2])
    let tag = (props[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
    var mode = reviewed == "pixels" ? "pixels" : "metadata"
    if reviewed == "automatic" && [3, 6, 8].contains(tag) {
        mode = orientationMode(tag:tag, raw:poses(thumbnail(args[2], maximum:1200, mode:"pixels")),
                               metadata:poses(thumbnail(args[2], maximum:1200)))
    }
    let image = thumbnail(args[2], maximum: 256, mode:mode)
    let tiff = props[kCGImagePropertyTIFFDictionary] as? NSDictionary
    let iptc = props[kCGImagePropertyIPTCDictionary] as? NSDictionary
    let description = (iptc?[kCGImagePropertyIPTCCaptionAbstract] as? String)
        ?? (tiff?[kCGImagePropertyTIFFImageDescription] as? String) ?? ""
    let normalized = raster(image, width: 64, height: 64)
    let small = raster(image, width: 8, height: 8)
    let wide = raster(image, width: 9, height: 8)
    var difference: UInt64 = 0
    func luminance(_ offset: Int) -> Int {
        return 299 * Int(wide[offset]) + 587 * Int(wide[offset + 1]) + 114 * Int(wide[offset + 2])
    }
    for y in 0..<8 { for x in 0..<8 {
        difference <<= 1
        if luminance((y * 9 + x) * 4) > luminance((y * 9 + x + 1) * 4) { difference |= 1 }
    } }
    var grid: [Int] = []
    for i in stride(from: 0, to: small.count, by: 4) {
        grid.append(contentsOf: [Int(small[i]), Int(small[i + 1]), Int(small[i + 2])])
    }
    printJSON(["version": 2, "width": image.width, "height": image.height,
        "orientationMode": mode, "description": String(description.prefix(256)),
        "pixelHash": SHA256.hash(data: Data(normalized)).map { String(format: "%02x", $0) }.joined(),
        "differenceHash": String(format: "%016llx", difference), "colorGrid": grid])
    exit(0)
}
guard args.count == 3,
      let data = try? Data(contentsOf: URL(fileURLWithPath: args[1])), data.count <= 65536,
      let manifest = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
      [1, 2].contains(manifest["version"] as? Int ?? 0),
      let photos = manifest["photos"] as? [[String: String]], (2...4).contains(photos.count),
      let color = CGColorSpace(name: CGColorSpace.sRGB),
      let canvas = CGContext(data: nil, width: 1920, height: 1080, bitsPerComponent: 8,
          bytesPerRow: 0, space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { fail() }
if manifest["version"] as? Int == 2 {
    let images: [CGImage] = photos.map { photo in
        guard let path = photo["path"], ["pixels", "metadata"].contains(photo["orientationMode"] ?? "") else { fail() }
        return thumbnail(path, maximum:1920, mode:photo["orientationMode"]!)
    }
    let seedText = manifest["seed"] as? String ?? "0"
    let seed = UInt64(seedText, radix:16) ?? 17
    let layout = scrapbookLayout(images.map { CGFloat($0.width)/CGFloat($0.height) }, seed:seed)
    canvas.setFillColor(CGColor(red:0.89, green:0.865, blue:0.81, alpha:1))
    canvas.fill(CGRect(x:0, y:0, width:1920, height:1080))
    // Quiet paper grain: deterministic, offline and cheap to prepare on the Mac.
    var grain = seed
    for _ in 0..<14000 {
        grain = grain &* 6364136223846793005 &+ 1
        let x = CGFloat((grain >> 16) % 1920), y = CGFloat((grain >> 40) % 1080)
        canvas.setFillColor(CGColor(gray:grain & 1 == 0 ? 0 : 1, alpha:0.035))
        canvas.fill(CGRect(x:x, y:y, width:2, height:1))
    }
    let ink = CGColor(red:0.22, green:0.23, blue:0.22, alpha:1)
    if let title = manifest["title"] as? String, title.count <= 80 {
        text(title, font:"Baskerville-Italic", size:42, color:ink,
             at:CGPoint(x:78,y:1004), width:1470, canvas:canvas)
    }
    for placement in layout {
        let photo = photos[placement.index], image = images[placement.index]
        let size = placement.size
        let rect = CGRect(x:-size.width/2, y:-size.height/2, width:size.width, height:size.height)
        canvas.saveGState(); canvas.translateBy(x:placement.center.x, y:placement.center.y)
        canvas.rotate(by:placement.angle)
        canvas.setShadow(offset:CGSize(width:4,height:-7), blur:15, color:CGColor(gray:0.12,alpha:0.35))
        canvas.setFillColor(CGColor(red:0.995,green:0.991,blue:0.976,alpha:1)); canvas.fill(rect)
        canvas.setShadow(offset:.zero, blur:0, color:nil)
        // Shape matches the source exactly; all four corners remain visible.
        canvas.interpolationQuality = .high
        canvas.draw(image, in:CGRect(x:rect.minX+15,y:rect.minY+67,width:size.width-30,height:size.height-82))
        let caption = photo["caption"] ?? ""
        guard caption.count <= 80 else { fail() }
        if let split = caption.range(of:" · ", options:.backwards) {
            text(String(caption[..<split.lowerBound]), font:"BradleyHandITCTT-Bold", size:28, color:ink,
                 at:CGPoint(x:rect.minX+22,y:rect.minY+37), width:size.width-44, canvas:canvas)
            text(String(caption[split.upperBound...]), font:"BradleyHandITCTT-Bold", size:22, color:ink,
                 at:CGPoint(x:rect.minX+22,y:rect.minY+13), width:size.width-44, canvas:canvas)
        } else {
            text(caption, font:"BradleyHandITCTT-Bold", size:31, color:ink,
                 at:CGPoint(x:rect.minX+22,y:rect.minY+24), width:size.width-44, canvas:canvas)
        }
        canvas.restoreGState()
    }
    guard let image = canvas.makeImage(), let output = CGImageDestinationCreateWithURL(
        URL(fileURLWithPath:args[2]) as CFURL,"public.jpeg" as CFString,1,nil) else { fail() }
    CGImageDestinationAddImage(output,image,[kCGImageDestinationLossyCompressionQuality:0.9] as CFDictionary)
    guard CGImageDestinationFinalize(output) else { fail() }
    printJSON(["version":2,"width":1920,"height":1080,"photos":photos.count,"frameFill":"scrapbook",
        "layout":layout.map { p in ["index":p.index,"x":p.center.x,"y":p.center.y,
            "width":p.size.width,"height":p.size.height,"angle":p.angle] as [String:Any] }])
    exit(0)
}
canvas.setFillColor(CGColor(red: 0.035, green: 0.06, blue: 0.1, alpha: 1))
canvas.fill(CGRect(x: 0, y: 0, width: 1920, height: 1080))
let left = CGFloat(16), bottom = CGFloat(16), width = CGFloat(936), half = CGFloat(516)
let cells: [CGRect]
switch photos.count {
case 2: cells = [CGRect(x: left, y: bottom, width: width, height: 1048),
                 CGRect(x: 968, y: bottom, width: width, height: 1048)]
case 3: cells = [CGRect(x: left, y: bottom, width: width, height: 1048),
                 CGRect(x: 968, y: 548, width: width, height: half),
                 CGRect(x: 968, y: bottom, width: width, height: half)]
default: cells = [CGRect(x: left, y: 548, width: width, height: half),
                  CGRect(x: 968, y: 548, width: width, height: half),
                  CGRect(x: left, y: bottom, width: width, height: half),
                  CGRect(x: 968, y: bottom, width: width, height: half)]
}
let renderer = CIContext(options: [.cacheIntermediates: false])
for (photo, cell) in zip(photos, cells) {
    guard let path = photo["path"], let caption = photo["caption"], caption.count <= 32 else { fail() }
    let image = thumbnail(path, maximum: 1920)
    canvas.saveGState()
    canvas.addPath(CGPath(roundedRect: cell, cornerWidth: 12, cornerHeight: 12, transform: nil))
    canvas.clip()
    let fill = max(cell.width / CGFloat(image.width), cell.height / CGFloat(image.height))
    let backdrop = CIImage(cgImage: image)
        .transformed(by: CGAffineTransform(scaleX: fill, y: fill))
        .transformed(by: CGAffineTransform(translationX: cell.midX - CGFloat(image.width) * fill / 2,
                                          y: cell.midY - CGFloat(image.height) * fill / 2))
        .clampedToExtent().applyingFilter("CIGaussianBlur", parameters: [kCIInputRadiusKey: 30.0])
    guard let blurred = renderer.createCGImage(backdrop, from: cell) else { fail() }
    canvas.draw(blurred, in: cell)
    canvas.setFillColor(CGColor(gray: 0, alpha: 0.35)); canvas.fill(cell)
    // Keep the entire sharp image clear of the decorative rounded-cell clipping.
    let fit = min((cell.width - 24) / CGFloat(image.width), (cell.height - 24) / CGFloat(image.height))
    let imageWidth = CGFloat(image.width) * fit, imageHeight = CGFloat(image.height) * fit
    canvas.interpolationQuality = .high
    canvas.draw(image, in: CGRect(x: cell.midX - imageWidth / 2, y: cell.midY - imageHeight / 2,
                                 width: imageWidth, height: imageHeight))
    let font = CTFontCreateWithName("HelveticaNeue-Medium" as CFString, 28, nil)
    let text = NSAttributedString(string: caption, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 1, alpha: 1)])
    let line = CTLineCreateWithAttributedString(text)
    let labelWidth = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil)) + 24
    let tag = CGRect(x: cell.minX + 14, y: cell.maxY - 56, width: labelWidth, height: 40)
    canvas.setFillColor(CGColor(gray: 0, alpha: 0.65))
    canvas.addPath(CGPath(roundedRect: tag, cornerWidth: 7, cornerHeight: 7, transform: nil)); canvas.fillPath()
    canvas.textMatrix = .identity; canvas.textPosition = CGPoint(x: tag.minX + 12, y: tag.minY + 10)
    CTLineDraw(line, canvas)
    canvas.restoreGState()
}
guard let image = canvas.makeImage(),
      let output = CGImageDestinationCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL,
          "public.jpeg" as CFString, 1, nil) else { fail() }
CGImageDestinationAddImage(output, image, [kCGImageDestinationLossyCompressionQuality: 0.86] as CFDictionary)
guard CGImageDestinationFinalize(output) else { fail() }
printJSON(["version": 1, "width": 1920, "height": 1080, "photos": photos.count, "frameFill": "blur"])
