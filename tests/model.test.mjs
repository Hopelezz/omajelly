import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../Model.js", import.meta.url), "utf8");
const model = {};
vm.createContext(model);
vm.runInContext(source, model);

const MOVIE = "ddddddddddddddddddddddddddddddd1";
const SHOW = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeee1";

const document = {
  schemaVersion: 1,
  configured: true,
  sourceState: "updated",
  stale: false,
  lastSuccessAt: "2026-08-24T10:00:00Z",
  items: [
    {
      ratingKey: MOVIE,
      kind: "movie",
      title: "Arrival <script>",
      subtitle: "Movie · 2016",
      addedAt: "2026-08-24T09:00:00Z",
      addedLabel: "Today · 11:00",
      watchState: "unwatched",
      isNew: true,
    },
    {
      ratingKey: SHOW,
      kind: "show",
      title: "Silo",
      subtitle: "Show · S02E02 · Order",
      addedAt: "2026-08-23T09:00:00Z",
      addedLabel: "Yesterday",
      watchState: "watched",
      isNew: false,
    },
  ],
};

test("normalizes bounded plain-text media rows", () => {
  const value = model.normalizeDocument(document);
  assert.equal(value.items.length, 2);
  assert.equal(value.items[0].title, "Arrival ‹script›");
  assert.equal(value.newCount, 1);
  assert.equal(model.watchLabel(value.items[1].watchState), "WATCHED");
});

test("rejects invalid item ids and watch states", () => {
  const value = structuredClone(document);
  value.items.push({ ...value.items[0], ratingKey: "../42", watchState: "maybe" });
  value.items.push({ ...value.items[0], ratingKey: "42", watchState: "unwatched" });
  const normalized = model.normalizeDocument(value);
  assert.equal(normalized.items.length, 2);
});

test("accepts dashed Jellyfin GUIDs", () => {
  const value = structuredClone(document);
  value.items = [{
    ...value.items[0],
    ratingKey: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    playbackRatingKey: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  }];
  const normalized = model.normalizeDocument(value);
  assert.equal(normalized.items[0].ratingKey, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
});

test("updates a matching row watch state without mutating the input", () => {
  const value = model.normalizeDocument(document);
  const updated = model.updateWatchState(value.items, MOVIE, "watched");
  assert.notEqual(updated, value.items);
  assert.equal(updated[0].watchState, "watched");
  assert.equal(updated[0].isNew, false);
  assert.equal(value.items[0].watchState, "unwatched");
  assert.equal(updated[1], value.items[1]);
});

test("fuzzy-matches compact media metadata by term", () => {
  const item = model.normalizeDocument(document).items[0];
  assert.equal(model.matchesMediaQuery(item, "arrival 2016"), true);
  assert.equal(model.matchesMediaQuery(item, "arvl"), true);
  assert.equal(model.matchesMediaQuery(item, "show s01"), false);
});

test("reports source and freshness labels", () => {
  assert.equal(model.sourceLabel("updated", false), "LIVE");
  assert.equal(model.sourceLabel("offline", false), "OFFLINE");
  assert.equal(model.relativeTime("2026-08-24T10:00:00Z", Date.parse("2026-08-24T10:22:00Z")), "Updated 22m ago");
  assert.equal(model.tooltip({ configured: false, items: [], newCount: 0 }, false), "Omajelly · Setup required");
});

test("caps documents before QML retains them", () => {
  const value = structuredClone(document);
  value.items = Array.from({ length: 61 }, (_, index) => ({
    ...document.items[0],
    ratingKey: String(index + 1).padStart(8, "a"),
  }));
  assert.throws(() => model.normalizeDocument(value), /too many items/);
});

test("normalizes bounded activity views and browse pages", () => {
  const value = structuredClone(document);
  value.continueItems = [value.items[0]];
  value.movieItems = [value.items[0]];
  value.seriesItems = [value.items[1]];
  const normalized = model.normalizeDocument(value);
  assert.equal(normalized.continueItems.length, 1);
  assert.equal(normalized.seriesItems[0].kind, "show");

  const browse = model.normalizeBrowseDocument({
    schemaVersion: 1,
    kind: "shows",
    query: "sci-fi",
    offset: 0,
    limit: 40,
    total: 1,
    items: [{ ...value.items[1], playable: false }],
  });
  assert.equal(browse.items[0].playable, false);

  const search = model.normalizeBrowseDocument({
    ...browse,
    kind: "search",
    query: "show s01",
  });
  assert.equal(search.kind, "search");
});

test("keeps show folders and flattens accordion children in place", () => {
  const show = {
    ratingKey: SHOW,
    kind: "show",
    title: "Silo",
    subtitle: "Show · 10 episodes",
    addedAt: "2026-08-23T09:00:00Z",
    addedLabel: "",
    watchState: "unwatched",
    isNew: false,
    playable: false,
    showKey: SHOW,
  };
  const season = {
    ratingKey: "11111111111111111111111111111101",
    kind: "season",
    title: "Season 1",
    subtitle: "10 episodes",
    addedAt: "2026-08-23T09:00:00Z",
    addedLabel: "",
    watchState: "unwatched",
    isNew: false,
    playable: false,
    showKey: SHOW,
  };
  const episode = {
    ratingKey: "ffffffffffffffffffffffffffffff01",
    kind: "show",
    title: "Silo",
    subtitle: "Show · S01E01 · Opening",
    addedAt: "2026-08-23T09:00:00Z",
    addedLabel: "",
    watchState: "unwatched",
    isNew: false,
    playable: true,
    showKey: SHOW,
  };

  const seasons = model.normalizeBrowseDocument({
    schemaVersion: 1,
    kind: "seasons",
    query: "",
    offset: 0,
    limit: 40,
    total: 1,
    items: [season],
  });
  assert.equal(seasons.items[0].kind, "season");
  assert.equal(seasons.items[0].playable, false);
  assert.equal(seasons.items[0].showKey, SHOW);

  const folders = model.asShowFolders([{ ...show, ratingKey: episode.ratingKey, playable: true }]);
  assert.equal(folders[0].ratingKey, SHOW);
  assert.equal(folders[0].playable, false);

  const rows = model.flattenAccordion(
    folders,
    { [SHOW]: seasons.items, [season.ratingKey]: [episode] },
    SHOW,
    season.ratingKey,
  );
  assert.equal(rows.length, 3);
  assert.equal(rows[0].depth, 0);
  assert.equal(rows[1].kind, "season");
  assert.equal(rows[1].depth, 1);
  assert.equal(rows[2].depth, 2);
  assert.equal(rows[2].playable, true);
});
