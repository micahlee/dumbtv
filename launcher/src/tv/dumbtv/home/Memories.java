package tv.dumbtv.home;

import android.service.dreams.DreamService;

/** Opt-in offline photo screensaver. Android owns inactivity, playback suppression and power. */
public final class Memories extends DreamService {
    private MemoryFrame frame;
    @Override public void onAttachedToWindow() {
        super.onAttachedToWindow();
        Config cfg = Config.get(this); cfg.refresh();
        if (!"on".equals(cfg.get("memories.enabled", "off"))) { finish(); return; }
        setInteractive(false); setFullscreen(true); setScreenBright(true);
        frame = new MemoryFrame(this); setContentView(frame);
    }
    @Override public void onDetachedFromWindow() {
        if (frame != null) { frame.stop(); frame = null; }
        super.onDetachedFromWindow();
    }
}
