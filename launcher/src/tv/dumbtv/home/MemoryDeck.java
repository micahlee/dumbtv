package tv.dumbtv.home;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** No repeat until every current collage has been offered; survives review interludes. */
final class MemoryDeck {
    private final Set<String> played = new HashSet<>();
    private String last;
    synchronized List<MemoryDates.Photo> order(List<MemoryDates.Photo> photos) {
        Set<String> current = new HashSet<>();
        for (MemoryDates.Photo p : photos) current.add(p.file);
        played.retainAll(current);
        if (played.containsAll(current)) played.clear();
        List<MemoryDates.Photo> result = new ArrayList<>();
        for (MemoryDates.Photo p : photos) if (!played.contains(p.file)) result.add(p);
        Collections.shuffle(result);
        if (result.size() > 1 && result.get(0).file.equals(last)) Collections.swap(result, 0, 1);
        return result;
    }
    synchronized void shown(String file) { played.add(file); last = file; }
    synchronized void skip(String file) { played.add(file); }
}
