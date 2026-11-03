// macOS ImageIO handles HEIC/JPEG orientation and removes location/camera metadata from TV copies.
import Foundation
import ImageIO
import CoreGraphics
import CoreImage
import Vision

let flags = Set(CommandLine.arguments.dropFirst(3))
guard CommandLine.arguments.count >= 3 && flags.isSubset(of: ["--wallpaper", "--curate", "--blur-fill"])
else { fputs("usage: memory-image INPUT OUTPUT [--wallpaper] [--curate] [--blur-fill]\n", stderr); exit(2) }
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
guard let source = CGImageSourceCreateWithURL(input as CFURL, nil) else { exit(3) }
let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
let exif = props?[kCGImagePropertyExifDictionary] as? [CFString: Any]
let taken = exif?[kCGImagePropertyExifDateTimeOriginal] as? String
let options: [CFString: Any] = [
    kCGImageSourceCreateThumbnailFromImageAlways: true,
    kCGImageSourceCreateThumbnailWithTransform: true,
    kCGImageSourceThumbnailMaxPixelSize: 1920,
    kCGImageSourceShouldCacheImmediately: true
]
guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { exit(4) }
var curation: [String: Any]?
if flags.contains("--curate") {
    let labels = VNClassifyImageRequest(), faces = VNDetectFaceRectanglesRequest()
    let people = VNDetectHumanRectanglesRequest(); people.upperBodyOnly = false
    let text = VNRecognizeTextRequest(); text.recognitionLevel = .accurate
    do { try VNImageRequestHandler(cgImage: thumbnail, options: [:]).perform([labels, faces, people, text]) }
    catch { fputs("photo analysis failed\n", stderr); exit(7) }
    let scenes: Set<String> = ["outdoor", "land", "water_body", "sky", "landscape", "scenery",
        "mountain", "forest", "beach", "garden", "park", "building", "architecture", "city",
        "urban", "street", "bridge", "landmark", "interior", "living_room", "bedroom",
        "kitchen", "dining_room", "stadium", "seascape", "waterfall"]
    let documents: Set<String> = ["document", "handwriting", "screenshot", "printed_page",
        "receipt", "diagram", "chart"]
    func score(_ identifiers: Set<String>) -> Float {
        return (labels.results ?? []).filter { identifiers.contains($0.identifier) }
            .map { $0.confidence }.max() ?? 0
    }
    let blocks = (text.results ?? []).filter { ($0.topCandidates(1).first?.confidence ?? 0) >= 0.3 }
    // Presence and broad scene scores only: no identities, face embeddings or OCR strings leave Vision.
    curation = ["version": 1,
        "faces": (faces.results ?? []).filter { $0.confidence >= 0.6 }.count,
        "people": (people.results ?? []).filter { $0.confidence >= 0.6 }.count,
        "sceneScore": score(scenes), "documentScore": score(documents),
        "textBlocks": blocks.count,
        "textCoverage": min(1.0, blocks.reduce(0.0) { $0 + $1.boundingBox.width * $1.boundingBox.height })]
}
var image = thumbnail
if flags.contains("--wallpaper") || flags.contains("--blur-fill") {
    guard let color = CGColorSpace(name: CGColorSpace.sRGB),
          let canvas = CGContext(data: nil, width: 1920, height: 1080, bitsPerComponent: 8,
                                 bytesPerRow: 0, space: color,
                                 bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { exit(4) }
    canvas.setFillColor(CGColor(gray: 0, alpha: 1))
    canvas.fill(CGRect(x: 0, y: 0, width: 1920, height: 1080))
    if flags.contains("--blur-fill") {
        // Only the decorative backdrop is cropped. The sharp foreground below remains complete.
        let fill = max(1920.0 / Double(thumbnail.width), 1080.0 / Double(thumbnail.height))
        let backdrop = CIImage(cgImage: thumbnail)
            .transformed(by: CGAffineTransform(scaleX: fill, y: fill))
            .transformed(by: CGAffineTransform(translationX: (1920 - Double(thumbnail.width) * fill) / 2,
                                              y: (1080 - Double(thumbnail.height) * fill) / 2))
            .clampedToExtent()
            .applyingFilter("CIGaussianBlur", parameters: [kCIInputRadiusKey: 40.0])
        let context = CIContext(options: [.cacheIntermediates: false])
        guard let blurred = context.createCGImage(backdrop, from: CGRect(x: 0, y: 0, width: 1920, height: 1080))
        else { exit(8) }
        canvas.draw(blurred, in: CGRect(x: 0, y: 0, width: 1920, height: 1080))
        canvas.setFillColor(CGColor(gray: 0, alpha: 0.35))
        canvas.fill(CGRect(x: 0, y: 0, width: 1920, height: 1080))
    }
    let scale = min(1920.0 / Double(thumbnail.width), 1080.0 / Double(thumbnail.height))
    let width = Double(thumbnail.width) * scale, height = Double(thumbnail.height) * scale
    canvas.interpolationQuality = .high
    canvas.draw(thumbnail, in: CGRect(x: (1920 - width) / 2, y: (1080 - height) / 2,
                                      width: width, height: height))
    guard let composed = canvas.makeImage() else { exit(4) }
    image = composed
}
guard let destination = CGImageDestinationCreateWithURL(output as CFURL, "public.jpeg" as CFString, 1, nil) else { exit(4) }
CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
guard CGImageDestinationFinalize(destination) else { exit(5) }
var json: [String: Any] = ["width": image.width, "height": image.height,
    "sourceWidth": thumbnail.width, "sourceHeight": thumbnail.height,
    "frameFill": flags.contains("--blur-fill") ? "blur" : "black"]
if let curation = curation { json["curation"] = curation }
if let taken = taken { json["taken"] = String(taken.prefix(10)).replacingOccurrences(of: ":", with: "-") }
else { json["taken"] = NSNull() }
guard let data = try? JSONSerialization.data(withJSONObject: json), let text = String(data: data, encoding: .utf8) else { exit(6) }
print(text)
