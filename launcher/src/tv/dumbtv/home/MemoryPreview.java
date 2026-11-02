package tv.dumbtv.home;

import android.app.Activity;
import android.os.Bundle;
import android.view.KeyEvent;

/** Manual preview; Back or OK returns to the caller, and HOME uses the normal guard. */
public final class MemoryPreview extends Activity {
    private MemoryFrame frame;
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        Config cfg = Config.get(this); cfg.refresh();
        if (!"on".equals(cfg.get("memories.enabled", "off"))) { finish(); return; }
        frame = new MemoryFrame(this); setContentView(frame);
    }
    @Override public boolean onKeyDown(int code, KeyEvent event) {
        if (code == KeyEvent.KEYCODE_BACK || code == KeyEvent.KEYCODE_DPAD_CENTER
                || code == KeyEvent.KEYCODE_ENTER) { finish(); return true; }
        return super.onKeyDown(code, event);
    }
    @Override protected void onDestroy() {
        if (frame != null) frame.stop();
        super.onDestroy();
    }
}
