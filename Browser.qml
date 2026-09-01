import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "." as JellyCore
import "Model.js" as Model

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  property bool focusPrimed: false
  property string browseKind: "movies"
  property string query: ""
  property int offset: 0
  property int limit: 40
  property int total: 0
  property int selectedIndex: 0
  property var items: []
  property var displayItems: []
  property string expandedShowKey: ""
  property string expandedSeasonKey: ""
  property bool loading: false
  property bool reloadQueued: false
  property string error: ""
  property string _browseOutput: ""
  property string _browseError: ""
  property string _requestedKind: ""
  property string _requestedScope: ""
  property string _requestedQuery: ""
  property int _requestedOffset: 0

  readonly property string pluginRoot: Quickshell.env("HOME")
    + "/.config/omarchy/plugins/io.github.hopelezz.omajelly"
  readonly property string helperCommand: pluginRoot + "/bin/omajelly"
  readonly property bool searching: query.trim() !== ""
  readonly property string requestKind: searching ? "search" : browseKind
  readonly property string searchScope: browseKind === "shows" ? "shows" : "movies"
  readonly property bool hasPrevious: offset > 0
  readonly property bool hasNext: offset + items.length < total
  readonly property color onScrim: "white"
  readonly property color onScrimDim: Qt.rgba(1, 1, 1, 0.58)
  readonly property color onScrimUrgent: "#ff6b6b"

  function open(payloadJson) {
    var payload = {}
    try { payload = JSON.parse(payloadJson || "{}") || {} } catch (e) {}
    browseKind = payload.view === "series" ? "shows" : "movies"
    query = ""
    offset = 0
    selectedIndex = 0
    expandedShowKey = ""
    expandedSeasonKey = ""
    focusPrimed = false
    opened = true
    focusPrimeTimer.restart()
    loadPage()
    Qt.callLater(function() { if (root.opened) keyCatcher.forceActiveFocus() })
  }

  function close() {
    opened = false
    focusPrimed = false
    focusPrimeTimer.stop()
    browseProcess.running = false
    searchTimer.stop()
    items = []
    displayItems = []
    expandedShowKey = ""
    expandedSeasonKey = ""
    error = ""
  }

  function dismiss() {
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "io.github.hopelezz.omajelly")
    else close()
  }

  function setKind(kind) {
    browseKind = kind === "shows" ? "shows" : "movies"
    query = ""
    offset = 0
    selectedIndex = 0
    expandedShowKey = ""
    expandedSeasonKey = ""
    loadPage()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function rebuildDisplay() {
    displayItems = browseKind === "shows"
      ? Model.flattenAccordion(
          items,
          JellyCore.JellyfinState.folderChildren,
          expandedShowKey,
          expandedSeasonKey
        )
      : items
    selectedIndex = Math.max(0, Math.min(selectedIndex, Math.max(0, displayItems.length - 1)))
  }

  function goBack() {
    if (expandedSeasonKey !== "") {
      expandedSeasonKey = ""
      rebuildDisplay()
      return
    }
    if (expandedShowKey !== "") {
      expandedShowKey = ""
      rebuildDisplay()
      return
    }
    if (hasPrevious) {
      previousPage()
      return
    }
    dismiss()
  }

  function goForward() {
    var item = displayItems.length > 0 ? displayItems[selectedIndex] : null
    if (item && item.playable === false && !isExpandedFolder(item)) {
      toggleFolder(item)
      return
    }
    nextPage()
  }

  function isExpandedFolder(item) {
    if (!item) return false
    var key = String(item.ratingKey || "")
    if (item.kind === "show") return expandedShowKey === key
    if (item.kind === "season") return expandedSeasonKey === key
    return false
  }

  function toggleFolder(item) {
    var key = String(item && item.ratingKey || "")
    if (!/^[0-9a-fA-F-]{8,48}$/.test(key)) return
    if (item.kind === "show") {
      if (expandedShowKey === key) {
        expandedShowKey = ""
        expandedSeasonKey = ""
        rebuildDisplay()
        return
      }
      expandedShowKey = key
      expandedSeasonKey = ""
      rebuildDisplay()
      JellyCore.JellyfinState.loadFolderChildren(key, "seasons")
      return
    }
    if (item.kind === "season") {
      if (expandedSeasonKey === key) {
        expandedSeasonKey = ""
        rebuildDisplay()
        return
      }
      expandedSeasonKey = key
      rebuildDisplay()
      JellyCore.JellyfinState.loadFolderChildren(key, "episodes")
    }
  }

  function loadPage() {
    if (!opened) return
    if (browseProcess.running) {
      reloadQueued = true
      return
    }
    reloadQueued = false
    _browseOutput = ""
    _browseError = ""
    error = ""
    loading = true
    _requestedKind = requestKind
    _requestedScope = searchScope
    _requestedQuery = query
    _requestedOffset = offset
    var command = [
      "timeout", "--signal=TERM", "25", helperCommand, "browse",
      "--kind", requestKind,
      "--query", query,
      "--offset", String(offset),
      "--limit", String(limit)
    ]
    if (searching) command.push("--search-scope", searchScope)
    browseProcess.command = command
    browseProcess.running = true
  }

  function applyPage(raw) {
    var document = Model.normalizeBrowseDocument(JSON.parse(String(raw || "")))
    if (document.kind !== requestKind) throw new Error("Jellyfin returned the wrong browser view")
    items = document.items
    total = document.total
    rebuildDisplay()
  }

  function moveSelection(delta) {
    if (displayItems.length === 0) return
    selectedIndex = (selectedIndex + delta + displayItems.length) % displayItems.length
    Qt.callLater(function() { browserList.positionViewAtIndex(selectedIndex, ListView.Contain) })
  }

  function activate(item) {
    if (!item) return
    if (item.playable === false) {
      toggleFolder(item)
      return
    }
    JellyCore.JellyfinState.playItem(item, JellyCore.JellyfinState.playbackMode)
  }

  function previousPage() {
    if (!hasPrevious || loading) return
    offset = Math.max(0, offset - limit)
    selectedIndex = 0
    expandedShowKey = ""
    expandedSeasonKey = ""
    loadPage()
  }

  function nextPage() {
    if (!hasNext || loading) return
    offset += limit
    selectedIndex = 0
    expandedShowKey = ""
    expandedSeasonKey = ""
    loadPage()
  }

  Timer {
    id: searchTimer
    interval: 350
    repeat: false
    onTriggered: {
      root.offset = 0
      root.selectedIndex = 0
      root.expandedShowKey = ""
      root.expandedSeasonKey = ""
      root.loadPage()
    }
  }

  Timer {
    id: focusPrimeTimer
    interval: 75
    onTriggered: {
      if (!root.opened) return
      root.focusPrimed = true
      keyCatcher.forceActiveFocus()
    }
  }

  Connections {
    target: JellyCore.JellyfinState
    function onPlayingChanged() {
      if (!JellyCore.JellyfinState.playing && root.opened) Qt.callLater(root.loadPage)
    }
    function onFolderChildrenChanged() { if (root.opened) root.rebuildDisplay() }
  }

  Process {
    id: browseProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: browseStdout
      waitForEnd: true
      onStreamFinished: root._browseOutput = text
    }
    stderr: StdioCollector {
      id: browseStderr
      waitForEnd: true
      onStreamFinished: root._browseError = text
    }
    onExited: function(exitCode) {
      root.loading = false
      if (root.reloadQueued) {
        Qt.callLater(root.loadPage)
        return
      }
      if (root._requestedKind !== root.requestKind
          || root._requestedScope !== root.searchScope
          || root._requestedQuery !== root.query
          || root._requestedOffset !== root.offset) {
        Qt.callLater(root.loadPage)
        return
      }
      var stdout = String(root._browseOutput || browseStdout.text || "")
      var stderr = String(root._browseError || browseStderr.text || "")
      if (exitCode !== 0) {
        root.error = Model.plainText(stderr || "Could not browse Jellyfin", 220)
        return
      }
      try { root.applyPage(stdout) }
      catch (e) { root.error = Model.plainText(e, 220) }
    }
  }

  PanelWindow {
    id: browserWindow
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-jellyfin-browser"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened
      ? (root.focusPrimed ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive)
      : WlrKeyboardFocus.None

    Rectangle {
      anchors.fill: parent
      color: Qt.rgba(0, 0, 0, 0.86)

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true

      Keys.onEscapePressed: root.goBack()
      Keys.onUpPressed: root.moveSelection(-1)
      Keys.onDownPressed: root.moveSelection(1)
      Keys.onLeftPressed: root.goBack()
      Keys.onRightPressed: root.goForward()
      Keys.onReturnPressed: if (root.displayItems.length > 0) root.activate(root.displayItems[root.selectedIndex])
      Keys.onEnterPressed: if (root.displayItems.length > 0) root.activate(root.displayItems[root.selectedIndex])
      Keys.onPressed: function(event) {
        var text = String(event.text || "")
        if (event.key === Qt.Key_J || text === "j" || text === "J") {
          root.moveSelection(1); event.accepted = true
        } else if (event.key === Qt.Key_K || text === "k" || text === "K") {
          root.moveSelection(-1); event.accepted = true
        } else if (text === "/") { searchField.forceActiveFocus(); event.accepted = true }
        else if (text === "m" || text === "M") { root.setKind("movies"); event.accepted = true }
        else if (text === "s" || text === "S") { root.setKind("shows"); event.accepted = true }
        else if (text === "n" || text === "N") { root.nextPage(); event.accepted = true }
        else if (text === "p" || text === "P") { root.previousPage(); event.accepted = true }
      }

      Rectangle {
        id: browserCard
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(64), Style.space(1080))
        height: Math.min(parent.height - Style.space(64), Style.space(760))
        radius: Style.cornerRadius
        color: Qt.rgba(0.055, 0.055, 0.065, 0.98)
        border.width: Math.max(1, Style.space(1))
        border.color: Qt.rgba(1, 1, 1, 0.15)

        MouseArea {
          z: -1
          anchors.fill: parent
          onClicked: {}
        }

        Column {
          anchors.fill: parent
          anchors.margins: Style.space(24)
          spacing: Style.space(12)

          Item {
            width: parent.width
            implicitHeight: Math.max(browserTitle.implicitHeight, closeButton.implicitHeight)

            Column {
              id: browserTitle
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                text: "Browse Jellyfin"
                textFormat: Text.PlainText
                color: root.onScrim
                font.family: Style.font.family
                font.pixelSize: Style.font.display
                font.bold: true
              }

              Text {
                text: root.searching
                  ? (root.searchScope === "movies" ? "SEARCH MOVIES" : "SEARCH SHOWS")
                  : (root.browseKind === "movies" ? "ALL MOVIES" : "ALL SHOWS")
                textFormat: Text.PlainText
                color: root.onScrimDim
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                font.letterSpacing: 1.5
              }
            }

            Button {
              id: closeButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: root.expandedShowKey !== "" ? "Back  Esc / ←" : "Close  Esc"
              foreground: root.onScrim
              fontFamily: Style.font.family
              bordered: true
              onClicked: root.goBack()
            }
          }

          Row {
            spacing: Style.space(6)

            Button {
              text: "Movies"
              foreground: root.onScrim
              fontFamily: Style.font.family
              bordered: true
              active: root.browseKind === "movies"
              onClicked: root.setKind("movies")
            }

            Button {
              text: "Shows"
              foreground: root.onScrim
              fontFamily: Style.font.family
              bordered: true
              active: root.browseKind === "shows"
              onClicked: root.setKind("shows")
            }
          }

          Item {
            width: parent.width
            implicitHeight: searchField.implicitHeight

            TextField {
              id: searchField
              anchors.left: parent.left
              width: parent.width
              text: root.query
              maximumLength: 80
              placeholderText: root.searchScope === "movies"
                ? "Fuzzy-search movies  /" : "Fuzzy-search shows  /"
              foreground: root.onScrim
              font.family: Style.font.family
              onTextChanged: {
                root.query = text
                searchTimer.restart()
              }
              Keys.onDownPressed: {
                keyCatcher.forceActiveFocus()
                root.moveSelection(1)
              }
              Keys.onUpPressed: {
                keyCatcher.forceActiveFocus()
                root.moveSelection(-1)
              }
              Keys.onEscapePressed: {
                if (text !== "") text = ""
                else keyCatcher.forceActiveFocus()
              }
            }
          }

          Text {
            visible: root.error !== "" || JellyCore.JellyfinState.folderError !== ""
            width: parent.width
            text: Model.plainText(root.error || JellyCore.JellyfinState.folderError, 220)
            textFormat: Text.PlainText
            color: root.onScrimUrgent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Item {
            width: parent.width
            height: Math.max(
              Style.space(80),
              parent.height - y - browserFooter.implicitHeight - parent.spacing
            )

            Text {
              visible: root.loading || (!root.loading && root.displayItems.length === 0)
              anchors.fill: parent
              text: root.loading ? "Loading Jellyfin library…"
                : (JellyCore.JellyfinState.folderLoadingKey !== ""
                  ? "Opening folder…" : "No matching media")
              textFormat: Text.PlainText
              color: root.onScrimDim
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              verticalAlignment: Text.AlignVCenter
            }

            ListView {
              id: browserList
              visible: !root.loading && root.displayItems.length > 0
              anchors.fill: parent
              clip: true
              spacing: Style.space(4)
              model: root.displayItems
              currentIndex: root.selectedIndex
              boundsBehavior: Flickable.StopAtBounds
              interactive: contentHeight > height

              ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

              delegate: CursorSurface {
                id: mediaRow
                required property var modelData
                required property int index
                width: browserList.width
                implicitHeight: Style.space(54)
                foreground: root.onScrim
                hasCursor: root.selectedIndex === index

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onEntered: {
                    root.selectedIndex = mediaRow.index
                    keyCatcher.forceActiveFocus()
                  }
                  onClicked: {
                    keyCatcher.forceActiveFocus()
                    root.activate(mediaRow.modelData)
                  }
                }

                Text {
                  id: kindIcon
                  width: Style.space(28)
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(10) + (mediaRow.modelData.depth || 0) * Style.space(18)
                  anchors.verticalCenter: parent.verticalCenter
                  text: Model.itemIcon(mediaRow.modelData)
                  textFormat: Text.PlainText
                  color: Color.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.title
                  horizontalAlignment: Text.AlignHCenter
                }

                Column {
                  anchors.left: kindIcon.right
                  anchors.leftMargin: Style.space(10)
                  anchors.right: watchState.left
                  anchors.rightMargin: Style.space(14)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(1)

                  Text {
                    width: parent.width
                    text: Model.plainText(mediaRow.modelData.title, 256)
                    textFormat: Text.PlainText
                    color: root.onScrim
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    font.bold: mediaRow.modelData.watchState !== "watched"
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    text: Model.plainText(mediaRow.modelData.subtitle, 256)
                    textFormat: Text.PlainText
                    color: root.onScrimDim
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                Text {
                  id: watchState
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(12)
                  anchors.verticalCenter: parent.verticalCenter
                  text: mediaRow.modelData.playable === false
                    ? (root.isExpandedFolder(mediaRow.modelData) ? "CLOSE" : "OPEN")
                    : Model.watchLabel(mediaRow.modelData.watchState)
                  textFormat: Text.PlainText
                  color: root.onScrimDim
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
              }
            }
          }

          Column {
            id: browserFooter
            width: parent.width
            spacing: Style.space(8)

            Text {
              id: browserKeys
              width: parent.width
              text: "↑/↓ move · ↵ open · ← back · → forward · M/S · / search · Esc close"
              textFormat: Text.PlainText
              color: root.onScrimDim
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
              elide: Text.ElideRight
            }

            Item {
              id: pager
              width: parent.width
              implicitHeight: Math.max(pageLabel.implicitHeight, pageButtons.implicitHeight)

              Text {
                id: pageLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: root.total === 0 ? "0 items"
                  : (root.offset + 1) + "–" + Math.min(root.offset + root.items.length, root.total) + " of " + root.total
                textFormat: Text.PlainText
                color: root.onScrimDim
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }

              Row {
                id: pageButtons
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                Button {
                  text: "Previous  ←"
                  foreground: root.onScrim
                  fontFamily: Style.font.family
                  bordered: true
                  enabled: root.hasPrevious && !root.loading
                  onClicked: root.previousPage()
                }

                Button {
                  text: "Next  →"
                  foreground: root.onScrim
                  fontFamily: Style.font.family
                  bordered: true
                  enabled: root.hasNext && !root.loading
                  onClicked: root.nextPage()
                }
              }
            }
          }
        }
      }
    }
  }
}
