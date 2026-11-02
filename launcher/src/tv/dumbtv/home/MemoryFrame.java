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
import java.util.Collections;
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
    private final Runnable tick = this::next;
    private boolean stopped;
    private String last;

    MemoryFrame(Context c) {
        super(c);
        root = new File(Config.get(c).dir, "memories");
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
                    if (photo != null && new File(root, photo.file).isFile()) all.add(photo);
                }
            } catch (java.io.IOException ignored) { /* Keep the clock if refresh has not arrived. */ }
            Calendar today = Calendar.getInstance();
            List<MemoryDates.Photo> photos = MemoryDates.choose(all, today);
            Collections.shuffle(photos);
            if (photos.size() > 1 && photos.get(0).file.equals(last)) Collections.swap(photos, 0, 1);
            Bitmap bitmap = null;
            MemoryDates.Photo selected = null;
            for (MemoryDates.Photo photo : photos) {
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                String path = new File(root, photo.file).getPath();
                BitmapFactory.decodeFile(path, bounds);
                if (bounds.outWidth <= 0 || bounds.outHeight <= 0
                        || bounds.outWidth > 4096 || bounds.outHeight > 4096) continue;
                BitmapFactory.Options opts = new BitmapFactory.Options();
                opts.inPreferredConfig = Bitmap.Config.RGB_565;
                opts.inSampleSize = 1;
                while (bounds.outWidth / opts.inSampleSize > 1920
                        || bounds.outHeight / opts.inSampleSize > 1920) opts.inSampleSize *= 2;
                bitmap = BitmapFactory.decodeFile(path, opts);
                if (bitmap != null) { selected = photo; break; }
            }
            final Bitmap ready = bitmap;
            final MemoryDates.Photo photo = selected;
            ui.post(() -> {
                if (stopped) return;
                if (photo != null) {
                    image.setImageBitmap(ready); last = photo.file;
                    if (MemoryDates.onThisDay(photo, today)) caption.setText("On this day · " + photo.year);
                    else {
                        Calendar date = Calendar.getInstance(); date.set(photo.year, photo.month - 1, photo.day);
                        caption.setText("Memories · " + new SimpleDateFormat("MMMM d, yyyy", Locale.getDefault()).format(date.getTime()));
                    }
                } else caption.setText("Photos will appear after the next refresh");
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
