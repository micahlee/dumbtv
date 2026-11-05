package tv.dumbtv.home;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
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
    private final ImageView image;
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
        image = new ImageView(c);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        addView(image, new LayoutParams(-1, -1));
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
                if (stopped) return;
                if (photo != null) {
                    image.setImageBitmap(ready); deck.shown(photo.file);
                    if (MemoryDates.onThisDay(photo, today)) caption.setText(photo.collage
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

    void stop() {
        stopped = true;
        ui.removeCallbacksAndMessages(null);
        io.shutdownNow();
        image.setImageDrawable(null);
    }
}
