package tv.dumbtv.home;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.FileInputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** One local clip. Muted before preparation/start; released on every exit. No network. */
final class WeatherVideoFrame extends LinearLayout implements SurfaceHolder.Callback {
    private final ForecastClip clip;
    private final Runnable complete;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final SurfaceView surface;
    private final FrameLayout picture;
    private final TextView hint;
    private final AudioManager audio;
    private MediaPlayer player;
    private boolean stopped, finished, prepared, muted = true, hasFocus;
    private int videoWidth, videoHeight;
    private final Runnable timeout = () -> finish();
    private final AudioManager.OnAudioFocusChangeListener focus = change -> {
        if (change < 0) mute();
    };
    WeatherVideoFrame(Context context, ForecastClip clip, Runnable complete) {
        super(context); this.clip = clip; this.complete = complete;
        audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        setOrientation(VERTICAL); setBackgroundColor(0xFF080E19);
        TextView heading = Ui.text(context, 19, 0xFFF2F5FC, Ui.MEDIUM);
        heading.setText("WYFF forecast · " + clip.title); heading.setPadding(24, 12, 24, 4);
        addView(heading, new LayoutParams(-1, -2));
        picture = new FrameLayout(context);
        surface = new SurfaceView(context); surface.getHolder().addCallback(this);
        picture.addView(surface, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        addView(picture, new LayoutParams(-1, 0, 1));
        hint = Ui.text(context, 17, 0xFFBBD6FF, Ui.MEDIUM);
        hint.setPadding(24, 8, 24, 12); hint.setFocusable(true); hint.setClickable(true);
        hint.setOnClickListener(v -> toggleSound()); addView(hint, new LayoutParams(-1, -2));
        updateHint();
        ui.postDelayed(timeout, 12000);
    }
    private void updateHint() {
        String date = new SimpleDateFormat("EEE h:mm a", Locale.getDefault()).format(new Date(clip.published));
        hint.setText((!prepared ? "Loading · " : muted ? "Muted · Press OK for sound · " : "Sound on · Press OK to mute · ")
                + "Back to Daily Review · WYFF " + date);
        setContentDescription("WYFF forecast, " + (!prepared ? "loading" : muted ? "muted" : "sound on"));
    }
    void toggleSound() {
        if (stopped || !prepared || player == null) return;
        if (!muted) { mute(); return; }
        if (audio == null || audio.requestAudioFocus(focus, AudioManager.STREAM_MUSIC,
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) return;
        hasFocus = true; muted = false; player.setVolume(1f, 1f); updateHint();
    }
    private void mute() {
        muted = true;
        if (player != null) try { player.setVolume(0f, 0f); } catch (IllegalStateException ignored) { }
        if (hasFocus && audio != null) { hasFocus = false; audio.abandonAudioFocus(focus); }
        updateHint();
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        if (stopped || player != null) return;
        MediaPlayer next = new MediaPlayer(); player = next;
        try {
            next.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MOVIE).build());
            next.setVolume(0f, 0f); next.setDisplay(holder);
            try (FileInputStream input = new FileInputStream(clip.file)) { next.setDataSource(input.getFD()); }
            next.setOnVideoSizeChangedListener((mp, width, height) -> {
                if (!stopped && player == mp) { videoWidth = width; videoHeight = height; fit(); }
            });
            next.setOnPreparedListener(mp -> {
                if (stopped || player != mp) return;
                if (System.currentTimeMillis() >= clip.expires || mp.getDuration() <= 0 || mp.getDuration() > 600000) {
                    finish(); return;
                }
                prepared = true; ui.removeCallbacks(timeout); mp.setVolume(0f, 0f);
                mp.setVideoScalingMode(MediaPlayer.VIDEO_SCALING_MODE_SCALE_TO_FIT);
                updateHint(); mp.start();
            });
            next.setOnCompletionListener(mp -> finish());
            next.setOnErrorListener((mp, what, extra) -> { finish(); return true; });
            next.prepareAsync();
        } catch (IOException | IllegalStateException | IllegalArgumentException error) { finish(); }
    }
    private void fit() {
        if (videoWidth <= 0 || videoHeight <= 0 || picture.getWidth() <= 0 || picture.getHeight() <= 0) return;
        float scale = Math.min(picture.getWidth() / (float) videoWidth, picture.getHeight() / (float) videoHeight);
        surface.setLayoutParams(new FrameLayout.LayoutParams(Math.round(videoWidth * scale),
                Math.round(videoHeight * scale), Gravity.CENTER));
    }
    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight); ui.post(this::fit);
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { }
    @Override public void surfaceDestroyed(SurfaceHolder holder) { if (!stopped) finish(); }
    private void finish() {
        if (stopped || finished) return;
        finished = true; mute(); ui.removeCallbacks(timeout); ui.post(() -> { if (!stopped) complete.run(); });
    }
    void stop() {
        if (stopped) return;
        stopped = true; ui.removeCallbacksAndMessages(null); mute();
        if (player != null) { player.release(); player = null; }
        surface.getHolder().removeCallback(this);
    }
}
