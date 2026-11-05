// Native, offline collage rendering and content fingerprints. Originals are read-only.
import Foundation
import ImageIO
import CoreGraphics
import CoreImage
import CoreText
import CryptoKit

func fail() -> Never { fputs("collage preparation failed\n", stderr); exit(1) }
func thumbnail(_ path: String, maximum: Int) -> CGImage {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
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
let args = CommandLine.arguments
if args.count == 3 && args[1] == "--fingerprint" {
    let image = thumbnail(args[2], maximum: 256)
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
    printJSON(["version": 1, "width": image.width, "height": image.height,
        "pixelHash": SHA256.hash(data: Data(normalized)).map { String(format: "%02x", $0) }.joined(),
        "differenceHash": String(format: "%016llx", difference), "colorGrid": grid])
    exit(0)
}
guard args.count == 3,
      let data = try? Data(contentsOf: URL(fileURLWithPath: args[1])), data.count <= 65536,
      let manifest = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
      manifest["version"] as? Int == 1,
      let photos = manifest["photos"] as? [[String: String]], (2...4).contains(photos.count),
      let color = CGColorSpace(name: CGColorSpace.sRGB),
      let canvas = CGContext(data: nil, width: 1920, height: 1080, bitsPerComponent: 8,
          bytesPerRow: 0, space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { fail() }
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
