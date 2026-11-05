package tv.dumbtv.home;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Local, bounded-size JPEG cache. Never connects to the network or reads another app's files. */
final class MemoryFrame extends FrameLayout {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final FrameLayout pictures;
    private final ImageView[] images = new ImageView[2];
    private int activeImage = -1;
    private Runnable dissolve;
    private final TextView clock, caption;
    private final File root;
    private final boolean fullColor;
    private final Runnable tick = this::next;
    private boolean stopped;
    private final MemoryDeck deck;
    private final boolean collagesOnly;
    private final Runnable unavailable;

    MemoryFrame(Context c) {
        this(c, new MemoryDeck(), false, null);
    }

    static boolean hasCollages(Context c) {
        File directory = new File(Config.get(c).dir, "memories");
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new FileInputStream(new File(directory, "index.txt")), StandardCharsets.UTF_8))) {
            for (int i = 0; i < 1000; i++) {
                String line = reader.readLine(); if (line == null) break;
                MemoryDates.Photo photo = MemoryDates.parse(line.trim());
                if (photo != null && photo.collage && new File(directory, photo.file).isFile()) return true;
            }
        } catch (java.io.IOException ignored) { /* Stay on review until a usable cache arrives. */ }
        return false;
    }

    MemoryFrame(Context c, MemoryDeck deck, boolean collagesOnly, Runnable unavailable) {
        super(c);
        this.deck = deck; this.collagesOnly = collagesOnly; this.unavailable = unavailable;
        root = new File(Config.get(c).dir, "memories");
        fullColor = "full".equals(Config.get(c).get("memories.color", "compact"));
        setBackgroundColor(0xFF000000);
        pictures = new FrameLayout(c); addView(pictures, new LayoutParams(-1, -1));
        for (int i = 0; i < images.length; i++) {
            images[i] = new ImageView(c); images[i].setScaleType(ImageView.ScaleType.FIT_CENTER);
            pictures.addView(images[i], new LayoutParams(-1, -1));
        }
        clock = Ui.text(c, 26, 0xFFFFFFFF, Ui.LIGHT);
        clock.setShadowLayer(6, 1, 1, 0xFF000000);
        LayoutParams cp = new LayoutParams(-2, -2, Gravity.TOP | Gravity.RIGHT);
        cp.setMargins(32, 28, 32, 0); addView(clock, cp);
        caption = Ui.text(c, 19, 0xFFFFFFFF, Ui.MEDIUM);
        caption.setShadowLayer(6, 1, 1, 0xFF000000);
        LayoutParams p = new LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM | Gravity.LEFT);
        p.setMargins(32, 0, 32, 28); addView(caption, p);
        next();
    }

    private void next() {
        if (stopped) return;
        clock.setText(android.text.format.DateFormat.getTimeFormat(getContext()).format(new java.util.Date()));
        io.execute(() -> {
            List<MemoryDates.Photo> all = new ArrayList<>();
            File index = new File(root, "index.txt");
            try (BufferedReader r = new BufferedReader(new InputStreamReader(
                    new FileInputStream(index), StandardCharsets.UTF_8))) {
                for (String line; (line = r.readLine()) != null && all.size() < 1000;) {
                    MemoryDates.Photo photo = MemoryDates.parse(line.trim());
                    if (photo != null && (!collagesOnly || photo.collage)
                            && new File(root, photo.file).isFile()) all.add(photo);
                }
            } catch (java.io.IOException ignored) { /* Keep the clock if refresh has not arrived. */ }
            Calendar today = Calendar.getInstance();
            List<MemoryDates.Photo> photos = deck.order(MemoryDates.choose(all, today));
            Bitmap bitmap = null;
            MemoryDates.Photo selected = null;
            for (MemoryDates.Photo photo : photos) {
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                String path = new File(root, photo.file).getPath();
                BitmapFactory.decodeFile(path, bounds);
                if (bounds.outWidth <= 0 || bounds.outHeight <= 0
                        || bounds.outWidth > 4096 || bounds.outHeight > 4096) { deck.skip(photo.file); continue; }
                BitmapFactory.Options opts = new BitmapFactory.Options();
                opts.inPreferredConfig = fullColor ? Bitmap.Config.ARGB_8888 : Bitmap.Config.RGB_565;
                opts.inSampleSize = 1;
                while (bounds.outWidth / opts.inSampleSize > 1920
                        || bounds.outHeight / opts.inSampleSize > 1920) opts.inSampleSize *= 2;
                bitmap = BitmapFactory.decodeFile(path, opts);
                if (bitmap != null) { selected = photo; break; }
                deck.skip(photo.file);
            }
            final Bitmap ready = bitmap;
            final MemoryDates.Photo photo = selected;
            ui.post(() -> {
                if (stopped) { if (ready != null) ready.recycle(); return; }
                if (photo != null) {
                    showPage(ready); deck.shown(photo.file);
                    clock.setTextColor(photo.scrapbook ? 0xFF383A38 : 0xFFFFFFFF);
                    clock.setShadowLayer(photo.scrapbook ? 0 : 6, 1, 1, 0xFF000000);
                    if (photo.scrapbook) caption.setText(""); // Factual dates are already on the paper and prints.
                    else if (MemoryDates.onThisDay(photo, today)) caption.setText(photo.collage
                            ? "On this day · Photo memories" : "On this day · " + photo.year);
                    else {
                        Calendar date = Calendar.getInstance(); date.set(photo.year, photo.month - 1, photo.day);
                        caption.setText("Memories · " + new SimpleDateFormat(photo.collage ? "MMMM d" : "MMMM d, yyyy",
                                Locale.getDefault()).format(date.getTime()));
                    }
                } else {
                    caption.setText("Photos will appear after the next refresh");
                    if (unavailable != null) { unavailable.run(); return; }
                }
                // FIT_CENTER can invalidate only the photo rectangle. Redraw the full frame
                // so text over black letterbox bars survives portrait/landscape transitions.
                invalidate();
                ui.postDelayed(tick, 15000);
            });
        });
    }

    private void showPage(Bitmap bitmap) {
        if (dissolve != null) ui.removeCallbacks(dissolve);
        int previous = activeImage, incoming = activeImage == 0 ? 1 : 0;
        ImageView next = images[incoming];
        next.setImageBitmap(bitmap); next.setTranslationX(0); next.setAlpha(1f);
        pictures.bringChildToFront(next); activeImage = incoming;
        if (previous < 0) return;
        ImageView old = images[previous];
        final long start = SystemClock.uptimeMillis();
        next.setAlpha(0f);
        dissolve = new Runnable() {
            @Override public void run() {
                if (stopped) return;
                float t = PhotoTransition.progress(SystemClock.uptimeMillis() - start);
                next.setAlpha(t); next.setTranslationX(getWidth() * .018f * (1f - t));
                old.setTranslationX(-getWidth() * .008f * t);
                if (t < 1f) ui.postDelayed(this, 16);
                else {
                    old.setImageDrawable(null); old.setTranslationX(0); old.setAlpha(1f);
                    next.setTranslationX(0); dissolve = null;
                }
            }
        };
        ui.post(dissolve);
    }

    void stop() {
        stopped = true;
        ui.removeCallbacksAndMessages(null);
        io.shutdownNow();
        dissolve = null;
        for (ImageView image : images) { image.setImageDrawable(null); image.setTranslationX(0); image.setAlpha(1f); }
    }
}
