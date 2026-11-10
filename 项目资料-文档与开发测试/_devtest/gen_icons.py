"""临时脚本（仅自检用）：生成标准样式星形 / 齿轮的精确 path，并解析法算出包围盒。
生成结果直接粘进 webui/js/icons.js，避免手算坐标导致中心偏移。
"""
import math


def fmt(v):
    s = "%.2f" % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def star_path(cx=12.0, cy=12.0, R=8.8, ratio=0.475, rot=-90.0, dy=0.7):
    """标准五角星：外径 R、内径 R*ratio、尖角朝上。"""
    r = R * ratio
    pts = []
    for k in range(5):
        ao = math.radians(rot + 72 * k)
        ai = math.radians(rot + 36 + 72 * k)
        pts.append((cx + R * math.cos(ao), cy + dy + R * math.sin(ao)))
        pts.append((cx + r * math.cos(ai), cy + dy + r * math.sin(ai)))
    d = "M%s %s" % (fmt(pts[0][0]), fmt(pts[0][1]))
    for p in pts[1:]:
        d += "L%s %s" % (fmt(p[0]), fmt(p[1]))
    return d + "Z", pts


def gear_path(cx=12.0, cy=12.0, R=8.6, r=6.8, teeth=8, tip_half=12.0, flank=5.0):
    """标准正齿轮轮廓：平顶齿 + 齿根圆弧，几何中心严格在 (cx, cy)。
    每个齿：齿顶弧 base±tip_half（半径 R）→ 齿侧斜线 → 齿根弧（半径 r）→ 下一齿。"""
    step = 360.0 / teeth
    root_half = (step / 2) - tip_half - flank

    def pt(ang_deg, rad):
        a = math.radians(ang_deg - 90.0)      # 让第 0 个齿朝正上方
        return (cx + rad * math.cos(a), cy + rad * math.sin(a))

    d = ""
    for i in range(teeth):
        base = i * step
        a0 = pt(base - tip_half, R)           # 齿顶弧起点
        a1 = pt(base + tip_half, R)           # 齿顶弧终点
        b0 = pt(base + tip_half + flank, r)   # 齿根弧起点
        b1 = pt(base + tip_half + flank + root_half, r)   # 齿根弧终点
        if i == 0:
            d += "M%s %s" % (fmt(a0[0]), fmt(a0[1]))
        d += "A%s %s 0 0 1 %s %s" % (fmt(R), fmt(R), fmt(a1[0]), fmt(a1[1]))
        d += "L%s %s" % (fmt(b0[0]), fmt(b0[1]))
        d += "A%s %s 0 0 1 %s %s" % (fmt(r), fmt(r), fmt(b1[0]), fmt(b1[1]))
        d += "L%s %s" % (fmt(a0[0] + (pt(base + step - tip_half, R)[0] - a0[0])),
                         fmt(pt(base + step - tip_half, R)[1]))
    return d + "Z"


def star_bbox(R=8.8, ratio=0.475, dy=0.7):
    r = R * ratio
    xs, ys = [], []
    for k in range(5):
        for rad, off in ((R, 0), (r, 36)):
            a = math.radians(-90 + off + 72 * k)
            xs.append(12 + rad * math.cos(a))
            ys.append(12 + dy + rad * math.sin(a))
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def gear_bbox(R=8.6, teeth=8, tip_half=12.0):
    xs, ys = [], []
    for i in range(teeth):
        for s in (-1, 1):
            a = math.radians(i * (360.0 / teeth) + s * tip_half - 90)
            xs.append(12 + R * math.cos(a))
            ys.append(12 + R * math.sin(a))
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def show(name, d, bb):
    x, y, w, h = bb
    print("%-8s bbox x %.2f y %.2f  w %.2f h %.2f  center (%.2f, %.2f)" %
          (name, x, y, w, h, x + w / 2, y + h / 2))
    print("  " + d)
    print()


if __name__ == "__main__":
    d, _ = star_path()
    show("star", d, star_bbox())
    show("star_solid", d, star_bbox())
    show("gear", gear_path(), gear_bbox())
