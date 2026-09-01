// Pure data rules shared by QML and the Node test suite.

var MAX_ITEMS = 60
var MAX_FIELD = 256
var MAX_KEY = 96

function plainText(value, maximum) {
  var limit = Math.max(0, Number(maximum) || MAX_FIELD)
  return String(value === undefined || value === null ? "" : value)
    .replace(/[\x00-\x1f\x7f]/g, " ")
    .replace(/</g, "‹")
    .replace(/>/g, "›")
    .replace(/&/g, "＆")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit)
}

function validTimestamp(value) {
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(String(value || ""))
}

function copyRow(item, depth) {
  var row = {}
  if (!item) return row
  Object.keys(item).forEach(function(key) { row[key] = item[key] })
  row.depth = Math.max(0, Math.min(4, Math.floor(Number(depth) || 0)))
  return row
}

function normalizeItem(value) {
  if (!value || (value.kind !== "movie" && value.kind !== "show" && value.kind !== "season"))
    return null
  var ratingKey = String(value.ratingKey || "")
  if (!/^[0-9a-fA-F-]{8,48}$/.test(ratingKey)) return null
  var playbackRatingKey = String(value.playbackRatingKey || ratingKey)
  if (!/^[0-9a-fA-F-]{8,48}$/.test(playbackRatingKey)) return null
  var watchState = String(value.watchState || "")
  if (["unwatched", "started", "watched"].indexOf(watchState) === -1) return null
  if (!validTimestamp(value.addedAt)) return null
  var title = plainText(value.title, MAX_FIELD)
  if (title === "") return null
  var item = {
    ratingKey: ratingKey,
    kind: value.kind,
    title: title,
    subtitle: plainText(value.subtitle, MAX_FIELD),
    addedAt: String(value.addedAt),
    addedLabel: plainText(value.addedLabel, 80),
    watchState: watchState,
    isNew: value.isNew === true,
    playbackRatingKey: playbackRatingKey,
    playbackHint: plainText(value.playbackHint, 80),
    playable: value.playable !== false,
    depth: Math.max(0, Math.min(4, Math.floor(Number(value.depth) || 0)))
  }
  var showKey = String(value.showKey || "")
  if (/^[0-9a-fA-F-]{8,48}$/.test(showKey)) item.showKey = showKey
  return item
}

function normalizeItems(rawItems, maximum) {
  if (!Array.isArray(rawItems) || rawItems.length > maximum)
    throw new Error("Jellyfin returned too many items")
  var items = []
  for (var i = 0; i < rawItems.length; i++) {
    var item = normalizeItem(rawItems[i])
    if (item) items.push(item)
  }
  return items
}

function normalizeDocument(value) {
  if (!value || value.schemaVersion !== 1) throw new Error("Unsupported Jellyfin data format")
  var items = normalizeItems(Array.isArray(value.items) ? value.items : [], MAX_ITEMS)
  var continueItems = normalizeItems(Array.isArray(value.continueItems) ? value.continueItems : [], MAX_ITEMS)
  var movieItems = normalizeItems(Array.isArray(value.movieItems)
    ? value.movieItems : items.filter(function(item) { return item.kind === "movie" }), MAX_ITEMS)
  var seriesItems = normalizeItems(Array.isArray(value.seriesItems)
    ? value.seriesItems : items.filter(function(item) { return item.kind === "show" }), MAX_ITEMS)
  var state = String(value.sourceState || "")
  if (["unconfigured", "empty", "updated", "saved", "offline"].indexOf(state) === -1)
    state = items.length > 0 ? "saved" : "empty"
  return {
    schemaVersion: 1,
    configured: value.configured === true,
    sourceState: state,
    stale: value.stale !== false,
    items: items,
    continueItems: continueItems,
    movieItems: movieItems,
    seriesItems: seriesItems,
    newCount: movieItems.concat(seriesItems).filter(function(item) { return item.isNew }).length,
    lastSuccessAt: validTimestamp(value.lastSuccessAt) ? String(value.lastSuccessAt) : "",
    error: plainText(value.error, 220)
  }
}

function normalizeBrowseDocument(value) {
  if (!value || value.schemaVersion !== 1) throw new Error("Unsupported Jellyfin browse format")
  var kind = String(value.kind || "")
  if (["movies", "shows", "seasons", "episodes", "search"].indexOf(kind) === -1)
    throw new Error("Unsupported Jellyfin browse kind")
  var offset = Math.max(0, Math.floor(Number(value.offset) || 0))
  var limit = Math.max(1, Math.min(MAX_ITEMS, Math.floor(Number(value.limit) || 40)))
  var total = Math.max(0, Math.floor(Number(value.total) || 0))
  return {
    schemaVersion: 1,
    kind: kind,
    query: plainText(value.query, 80),
    offset: offset,
    limit: limit,
    total: total,
    items: normalizeItems(Array.isArray(value.items) ? value.items : [], MAX_ITEMS)
  }
}

function watchLabel(value) {
  if (value === "watched") return "WATCHED"
  if (value === "started") return "STARTED"
  return "UNWATCHED"
}

function updateWatchState(items, ratingKey, watchState) {
  var key = String(ratingKey || "")
  if (!Array.isArray(items) || !/^[0-9a-fA-F-]{8,48}$/.test(key)
      || ["watched", "unwatched"].indexOf(watchState) === -1)
    return items
  return items.map(function(item) {
    if (!item || String(item.ratingKey || "") !== key) return item
    var updated = {}
    Object.keys(item).forEach(function(name) { updated[name] = item[name] })
    updated.watchState = watchState
    if (watchState === "watched") updated.isNew = false
    return updated
  })
}

function matchesMediaQuery(item, query) {
  var terms = plainText(query, 80).toLowerCase().split(/\s+/).filter(function(term) {
    return term !== ""
  })
  if (terms.length === 0) return true
  var haystack = [item && item.title, item && item.subtitle, item && item.addedLabel,
    item && item.playbackHint, item && item.kind].map(function(value) {
      return plainText(value, MAX_FIELD).toLowerCase()
    }).join(" ")
  var words = haystack.split(/\s+/)
  return terms.every(function(term) {
    if (haystack.indexOf(term) !== -1) return true
    return words.some(function(word) {
      var position = 0
      for (var index = 0; index < word.length && position < term.length; index++) {
        if (word[index] === term[position]) position += 1
      }
      return position === term.length
    })
  })
}

function asShowFolders(items) {
  if (!Array.isArray(items)) return []
  return items.map(function(item) {
    var row = copyRow(item, 0)
    if (row.kind === "show") {
      var key = String(item.showKey || item.ratingKey || "")
      row.ratingKey = key
      row.showKey = key
      row.playable = false
      if (!row.playbackHint) row.playbackHint = "Open seasons"
    }
    return row
  })
}

function flattenAccordion(items, childrenByParent, expandedShowKey, expandedSeasonKey) {
  var map = childrenByParent || {}
  var rows = []
  var list = Array.isArray(items) ? items : []
  var showKey = String(expandedShowKey || "")
  var seasonKey = String(expandedSeasonKey || "")
  for (var i = 0; i < list.length; i++) {
    var item = copyRow(list[i], 0)
    if (item.playable === false && item.kind === "show")
      item.expanded = String(item.ratingKey || "") === showKey
    rows.push(item)
    if (item.playable !== false || String(item.ratingKey || "") !== showKey) continue
    var seasons = Array.isArray(map[item.ratingKey]) ? map[item.ratingKey] : []
    for (var s = 0; s < seasons.length; s++) {
      var season = copyRow(seasons[s], 1)
      season.expanded = String(season.ratingKey || "") === seasonKey
      rows.push(season)
      if (String(season.ratingKey || "") !== seasonKey) continue
      var episodes = Array.isArray(map[season.ratingKey]) ? map[season.ratingKey] : []
      for (var e = 0; e < episodes.length; e++)
        rows.push(copyRow(episodes[e], 2))
    }
  }
  return rows
}

function itemIcon(item) {
  if (!item) return ""
  if (item.playable === false && (item.kind === "show" || item.kind === "season"))
    return item.expanded ? "󰅀" : "󰅂"
  if (item.kind === "movie") return "󰿎"
  return "󰐊"
}

function sourceLabel(sourceState, updating) {
  if (updating) return "UPDATING"
  if (sourceState === "updated") return "LIVE"
  if (sourceState === "saved") return "SAVED"
  if (sourceState === "offline") return "OFFLINE"
  if (sourceState === "unconfigured") return "SETUP"
  return "EMPTY"
}

function relativeTime(timestamp, nowMs) {
  if (!validTimestamp(timestamp)) return "No saved refresh"
  var then = Date.parse(timestamp)
  var now = Number(nowMs)
  if (!isFinite(now)) now = Date.now()
  var seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return "Updated just now"
  var minutes = Math.floor(seconds / 60)
  if (minutes < 60) return "Updated " + minutes + "m ago"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return "Updated " + hours + "h ago"
  return "Updated " + Math.floor(hours / 24) + "d ago"
}

function tooltip(document, updating) {
  if (!document.configured) return "Omajelly · Setup required"
  if (updating) return "Omajelly · Updating…"
  if (document.items.length === 0) return "Omajelly · No items"
  var count = document.newCount
  return "Omajelly · " + count + (count === 1 ? " new item" : " new items")
}
