package tv.dumbtv.home;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.View;

/** Small local vector symbols; no network assets, emoji fonts or image decoding. */
final class WeatherIcon extends View {
    private static final int SUN = 0xFFFFCF78, CLOUD = 0xFFCED9EA, WATER = 0xFF79BFFF;
    private final ReviewWeather.Kind kind;
    private final boolean day;
    private final int background;

    WeatherIcon(Context context, ReviewWeather.Kind kind, boolean day, int background, String description) {
        super(context); this.kind = kind; this.day = day; this.background = background;
        setContentDescription(description); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }
    @Override protected void onDraw(Canvas canvas) {
        float size = Math.min(getWidth(), getHeight());
        draw(canvas, (getWidth()-size)/2, (getHeight()-size)/2, size, kind, day, background);
    }
    static View precipitation(Context context) {
        View view = new View(context) {
            @Override protected void onDraw(Canvas canvas) {
                float size = Math.min(getWidth(), getHeight());
                drop(canvas, (getWidth()-size)/2, (getHeight()-size)/2, size);
            }
        };
        view.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); return view;
    }
    private static Paint paint(int color) {
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG); paint.setColor(color);
        paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND); return paint;
    }
    private static void sun(Canvas c, float x, float y, float radius, boolean day, int background) {
        Paint p = paint(SUN);
        c.drawCircle(x, y, radius, p);
        if (!day) { p.setColor(background); c.drawCircle(x+radius*.6f, y-radius*.4f, radius*.9f, p); return; }
        p.setStrokeWidth(2.5f);
        for (int i=0; i<8; i++) {
            double angle = i*Math.PI/4;
            c.drawLine(x+(radius+4)*(float)Math.cos(angle), y+(radius+4)*(float)Math.sin(angle),
                    x+(radius+9)*(float)Math.cos(angle), y+(radius+9)*(float)Math.sin(angle), p);
        }
    }
    private static void cloud(Canvas c, float y) {
        Paint p = paint(CLOUD); c.drawCircle(22, y+31, 11, p); c.drawCircle(34, y+24, 14, p);
        c.drawCircle(46, y+31, 10, p); c.drawRoundRect(new RectF(11, y+30, 56, y+45), 8, 8, p);
    }
    private static void flake(Canvas c, float x, float y) {
        Paint p = paint(0xFFD4EDFF); p.setStrokeWidth(2);
        c.drawLine(x-4, y, x+4, y, p); c.drawLine(x-2, y-3.5f, x+2, y+3.5f, p);
        c.drawLine(x-2, y+3.5f, x+2, y-3.5f, p);
    }
    static void drop(Canvas c, float x, float y, float size) {
        c.save(); c.translate(x, y); c.scale(size/64, size/64);
        Path path = new Path(); path.moveTo(32, 7); path.cubicTo(28, 18, 15, 33, 15, 43);
        path.cubicTo(15, 65, 49, 65, 49, 43); path.cubicTo(49, 33, 36, 18, 32, 7); path.close();
        c.drawPath(path, paint(WATER)); c.restore();
    }
    static void draw(Canvas c, float x, float y, float size, ReviewWeather.Kind kind, boolean day, int background) {
        c.save(); c.translate(x, y); c.scale(size/64, size/64);
        switch (kind) {
            case CLEAR: sun(c, 32, 32, 15, day, background); break;
            case PARTLY_CLOUDY: sun(c, 21, 21, 10, day, background); cloud(c, 6); break;
            case CLOUDY: cloud(c, 4); break;
            case RAIN:
            case ICE:
            case MIX:
                cloud(c, -6);
                if (kind != ReviewWeather.Kind.MIX) {
                    Paint rain = paint(WATER); rain.setStrokeWidth(3);
                    for (int i=0; i<3; i++) c.drawLine(22+i*12, 44, 18+i*12, 54, rain);
                } else { Paint rain = paint(WATER); rain.setStrokeWidth(3); c.drawLine(21, 44, 17, 54, rain); flake(c, 43, 52); }
                if (kind == ReviewWeather.Kind.ICE) { Paint ice = paint(0xFFD4EDFF); c.drawCircle(20, 60, 2, ice); c.drawCircle(43, 60, 2, ice); }
                break;
            case STORM:
                cloud(c, -5); Path bolt = new Path(); bolt.moveTo(34, 37); bolt.lineTo(25, 51);
                bolt.lineTo(34, 51); bolt.lineTo(29, 63); bolt.lineTo(46, 46); bolt.lineTo(37, 46);
                bolt.lineTo(41, 37); bolt.close(); c.drawPath(bolt, paint(SUN)); break;
            case SNOW: cloud(c, -6); flake(c, 21, 52); flake(c, 34, 56); flake(c, 47, 51); break;
            case FOG:
                cloud(c, -9); Paint fog = paint(CLOUD); fog.setStrokeWidth(3);
                c.drawLine(12, 43, 53, 43, fog); c.drawLine(18, 50, 48, 50, fog); c.drawLine(12, 57, 53, 57, fog); break;
            case WIND:
                Paint wind = paint(CLOUD); wind.setStyle(Paint.Style.STROKE); wind.setStrokeWidth(3);
                for (int i=0; i<3; i++) { Path path = new Path(); path.moveTo(10, 20+i*12); path.lineTo(41, 20+i*12);
                    path.cubicTo(58, 20+i*12, 53, 7+i*12, 44, 13+i*12); c.drawPath(path, wind); } break;
            default:
                Paint p = paint(CLOUD); p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(2); c.drawCircle(32, 32, 20, p);
                p.setStyle(Paint.Style.FILL); p.setTextSize(29); p.setTextAlign(Paint.Align.CENTER); c.drawText("?", 32, 42, p);
        }
        c.restore();
    }
}
