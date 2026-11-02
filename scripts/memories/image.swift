// macOS ImageIO handles HEIC/JPEG orientation and removes location/camera metadata from TV copies.
import Foundation
import ImageIO
import CoreGraphics

guard CommandLine.arguments.count == 3 else { fputs("usage: memory-image INPUT OUTPUT\n", stderr); exit(2) }
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
guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
      let destination = CGImageDestinationCreateWithURL(output as CFURL, "public.jpeg" as CFString, 1, nil)
else { exit(4) }
CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
guard CGImageDestinationFinalize(destination) else { exit(5) }
var json: [String: Any] = ["width": image.width, "height": image.height]
if let taken = taken { json["taken"] = String(taken.prefix(10)).replacingOccurrences(of: ":", with: "-") }
else { json["taken"] = NSNull() }
guard let data = try? JSONSerialization.data(withJSONObject: json), let text = String(data: data, encoding: .utf8) else { exit(6) }
print(text)
