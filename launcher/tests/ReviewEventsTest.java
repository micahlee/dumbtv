package tv.dumbtv.home;

import java.util.Arrays;
import java.util.List;

public final class ReviewEventsTest {
    private static ReviewEvents.Event event(String id, String title, String venue, String source) {
        return new ReviewEvents.Event(id, 100, 200, false, false, title, venue, source, source, "#336699");
    }
    private static void count(int expected, ReviewEvents.Event... events) {
        int actual = ReviewEvents.combine(Arrays.asList(events)).size();
        if (actual != expected) throw new AssertionError("Expected " + expected + " events, got " + actual);
    }
    public static void main(String[] args) {
        ReviewEvents.Event family = event("family-copy", "Clemson @ Syracuse", "", "Family");
        ReviewEvents.Event sports = event("sports-feed", "Clemson @ Syracuse", "Stadium", "Football");
        List<ReviewEvents.Event> merged = ReviewEvents.combine(Arrays.asList(family, sports));
        if (merged.size() != 1 || !merged.get(0).sourceLabels().equals("Family · Football")
                || !merged.get(0).location.equals("Stadium")) throw new AssertionError("cross-calendar copies");
        if (!family.location.isEmpty() || family.sources.size() != 1) throw new AssertionError("source mutation");
        count(1, family, event("another-id", "  CLEMSON\u00a0 @   Syracuse ", "", "Sports"));
        count(2, family, event("same-calendar-second-event", family.title, "", "Family"));
        count(2, sports, event("different-venue", sports.title, "Other stadium", "Other calendar"));
        count(3, sports, event("different-venue", sports.title, "Other stadium", "Other calendar"), family);
        count(3, family, sports, event("different-venue", sports.title, "Other stadium", "Other calendar"));
        count(2, family, new ReviewEvents.Event("different-time", 110, 200, false, false,
                family.title, "", "Other", "Other", "#336699"));
        count(2, family, new ReviewEvents.Event("different-end", 100, 210, false, false,
                family.title, "", "Other", "Other", "#336699"));
        count(2, family, new ReviewEvents.Event("all-day", 100, 200, true, false,
                family.title, "", "Other", "Other", "#336699"));
        count(2, event("a", "Untitled event", "", "Family"), event("b", "Untitled event", "", "Other"));
        count(2, new ReviewEvents.Event("a", 100, 200, false, true, "Busy", "", "A", "A", "#336699"),
                new ReviewEvents.Event("b", 100, 200, false, true, "Busy", "", "B", "B", "#336699"));
        count(1, family, family);
        count(1, family, sports, sports);
        ReviewEvents.Event sameLabel = event("third-copy", family.title, "", "Another family calendar");
        sameLabel.sources.clear(); sameLabel.sources.put("third", "Family");
        merged = ReviewEvents.combine(Arrays.asList(family, sports, sameLabel));
        if (merged.size() != 1 || merged.get(0).sources.size() != 3
                || !merged.get(0).sourceLabels().equals("Family · Football")) throw new AssertionError("source labels");
        System.out.println("ReviewEventsTest passed: copies, source labels, times, venues, ambiguity and source immutability");
    }
}
