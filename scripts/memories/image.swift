// macOS ImageIO handles HEIC/JPEG orientation and removes location/camera metadata from TV copies.
import Foundation
import ImageIO
import CoreGraphics

guard CommandLine.arguments.count == 3 || (CommandLine.arguments.count == 4 && CommandLine.arguments[3] == "--wallpaper")
else { fputs("usage: memory-image INPUT OUTPUT [--wallpaper]\n", stderr); exit(2) }
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
var image = thumbnail
if CommandLine.arguments.count == 4 {
    guard let color = CGColorSpace(name: CGColorSpace.sRGB),
          let canvas = CGContext(data: nil, width: 1920, height: 1080, bitsPerComponent: 8,
                                 bytesPerRow: 0, space: color,
                                 bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { exit(4) }
    canvas.setFillColor(CGColor(gray: 0, alpha: 1))
    canvas.fill(CGRect(x: 0, y: 0, width: 1920, height: 1080))
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
var json: [String: Any] = ["width": image.width, "height": image.height]
if let taken = taken { json["taken"] = String(taken.prefix(10)).replacingOccurrences(of: ":", with: "-") }
else { json["taken"] = NSNull() }
guard let data = try? JSONSerialization.data(withJSONObject: json), let text = String(data: data, encoding: .utf8) else { exit(6) }
print(text)
