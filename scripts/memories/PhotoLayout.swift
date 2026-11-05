// Pure scrapbook geometry and conservative EXIF repair policy. No identities are inferred.
import Foundation
import CoreGraphics

struct FacePose {
    let confidence: Double, area: Double, roll: Double?
}
func orientationMode(tag: Int, raw: [FacePose], metadata: [FacePose]) -> String {
    guard [3, 6, 8].contains(tag) else { return "metadata" }
    func upright(_ faces: [FacePose], degrees: Double) -> Double {
        return faces.compactMap { face -> Double? in
            guard face.confidence >= 0.70, face.area >= 0.005,
                  let roll = face.roll, abs(roll) <= degrees * .pi / 180 else { return nil }
            return face.confidence * sqrt(face.area)
        }.max() ?? 0
    }
    let evidence = upright(raw, degrees: 30)
    return evidence > 0 && upright(metadata, degrees: 45) < evidence * 0.35 ? "pixels" : "metadata"
}
struct PrintPlacement {
    let index: Int, center: CGPoint, size: CGSize, angle: CGFloat
    var bounds: CGRect {
        let w = abs(cos(angle)) * size.width + abs(sin(angle)) * size.height
        let h = abs(sin(angle)) * size.width + abs(cos(angle)) * size.height
        return CGRect(x: center.x-w/2, y: center.y-h/2, width: w, height: h)
    }
}
func scrapbookLayout(_ aspects: [CGFloat], seed: UInt64) -> [PrintPlacement] {
    let portraits = aspects.indices.filter { aspects[$0] < 0.9 }
    let landscapes = aspects.indices.filter { aspects[$0] >= 0.9 }
    // Slots vary by the actual photo shapes, rather than rotating/cropping a photo to fit.
    var slots: [(Int, CGFloat, CGFloat, CGFloat, CGFloat)] = []
    let n = aspects.count
    if n == 2 {
        slots = [(0, 555, 510, 820, 740), (1, 1370, 505, 820, 720)]
    } else if n == 3 || portraits.count >= 3 {
        let ordered = portraits + landscapes
        let step = n == 3 ? CGFloat(590) : CGFloat(450)
        for (j, i) in ordered.enumerated() {
            slots.append((i, 960 + (CGFloat(j)-CGFloat(n-1)/2)*step,
                          [510, 540, 485, 520][j], n == 3 ? 550 : 410, 720))
        }
    } else if portraits.count == 2 {
        slots = [(portraits[0], 320, 515, 420, 740), (landscapes[0], 970, 735, 800, 325),
                 (landscapes[1], 985, 292, 780, 330), (portraits[1], 1630, 490, 410, 730)]
    } else if portraits.count == 1 {
        slots = [(portraits[0], 330, 510, 450, 740), (landscapes[0], 905, 725, 570, 330),
                 (landscapes[1], 1515, 720, 570, 340), (landscapes[2], 1190, 285, 840, 330)]
    } else {
        slots = [(0, 535, 730, 820, 340), (1, 1390, 705, 810, 340),
                 (2, 485, 285, 760, 335), (3, 1305, 295, 850, 335)]
    }
    var state = seed == 0 ? 17 : seed
    func random() -> CGFloat {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return CGFloat((state >> 32) % 1000) / 999
    }
    return slots.enumerated().map { order, slot in
        let (i, x, y, maxWidth, maxHeight) = slot
        let aspect = aspects[i]
        let h = min(maxHeight, maxWidth/aspect), w = h*aspect
        let angle = (CGFloat(order % 2 == 0 ? -1 : 1) * (2.0 + random()*2.0)) * .pi/180
        let size = CGSize(width: w+30, height: h+82)
        var center = CGPoint(x: x + (random()-0.5)*12, y: y + (random()-0.5)*10)
        let candidate = PrintPlacement(index:i, center:center, size:size, angle:angle).bounds
        center.x += max(0, 42-candidate.minX) - max(0, candidate.maxX-1878)
        center.y += max(0, 40-candidate.minY) - max(0, candidate.maxY-958)
        return PrintPlacement(index:i, center:center, size:size, angle:angle)
    }
}
