import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
import "." as JellyCore
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.hopelezz.omajelly"
  ipcTarget: "io.github.hopelezz.omajelly"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property int selectedIndex: 0
  property bool cursorActive: true
  property bool showWatched: true
  property bool helpOpen: false
  property bool mediaSearchOpen: false
  property string mediaQuery: ""
  property string activeView: "continue"
  property alias settingsOpen: settingsOverlay.opened
  property string expandedShowKey: ""
  property string expandedSeasonKey: ""

  readonly property var sourceItems: activeView === "movies"
    ? JellyCore.JellyfinState.movieItems
    : (activeView === "series" ? JellyCore.JellyfinState.seriesItems
      : (activeView === "recent" ? JellyCore.JellyfinState.items : JellyCore.JellyfinState.continueItems))
  readonly property var watchFilteredItems: showWatched
    ? sourceItems
    : sourceItems.filter(function(item) { return item.watchState !== "watched" })
  readonly property var visibleItems: {
    var source = watchFilteredItems.filter(function(item) {
      return Model.matchesMediaQuery(item, mediaQuery)
    })
    if (activeView !== "series") return source
    return Model.flattenAccordion(
      Model.asShowFolders(source),
      JellyCore.JellyfinState.folderChildren,
      expandedShowKey,
      expandedSeasonKey
    )
  }
  readonly property int watchedCount: sourceItems.filter(function(item) {
    return item.watchState === "watched"
  }).length
  readonly property string activeViewTitle: activeView === "movies"
    ? "RECENT MOVIES" : (activeView === "series" ? "RECENT SHOWS"
      : (activeView === "recent" ? "RECENTLY ADDED" : "CONTINUE WATCHING"))
  readonly property bool showNewItemCount: setting("showNewItemCount", true) !== false
  readonly property bool autoPlayNextEpisode:
    setting("autoPlayNextEpisode", false) === true
  readonly property string subtitleSearchLanguage: {
    var value = String(setting("subtitleSearchLanguage", "en") || "").toLowerCase()
    return /^[a-z]{2}$/.test(value) ? value : "en"
  }
  readonly property var barIdentity: hostWidget || root
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property color dimForeground: Qt.darker(contentForeground, 1.55)
  readonly property color urgentForeground: bar ? bar.urgent : Color.urgent
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  function open() {
    var showSettings = JellyCore.JellyfinState.settingsRequested
      || (JellyCore.JellyfinState.initialized && !JellyCore.JellyfinState.configured)
    JellyCore.JellyfinState.settingsRequested = false
    root.controller.show()
    root.clampSelection()
    if (!JellyCore.JellyfinState.initialized) JellyCore.JellyfinState.loadStatus()
    JellyCore.JellyfinState.checkPlayerWindow()
    if (showSettings)
      root.openSettings()
    else {
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
      if (JellyCore.JellyfinState.configured) Qt.callLater(JellyCore.JellyfinState.refresh)
    }
  }

  function close() {
    mediaSearchOpen = false
    mediaQuery = ""
    root.controller.hide()
  }
  function toggle() { if (root.opened) root.close(); else root.open() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function clampSelection() {
    selectedIndex = Math.max(0, Math.min(selectedIndex, Math.max(0, root.visibleItems.length - 1)))
  }

  function focusItem(index) {
    cursorActive = true
    selectedIndex = Math.max(0, Math.min(Number(index), Math.max(0, root.visibleItems.length - 1)))
    keyCatcher.forceActiveFocus()
    Qt.callLater(function() { mediaList.positionViewAtIndex(selectedIndex, ListView.Contain) })
  }

  function moveSelection(direction) {
    var count = root.visibleItems.length
    if (count === 0) return
    selectedIndex = (selectedIndex + direction + count) % count
    cursorActive = true
    Qt.callLater(function() { mediaList.positionViewAtIndex(selectedIndex, ListView.Contain) })
  }

  function playSelection() {
    if (root.visibleItems.length > 0)
      root.activateItem(root.visibleItems[selectedIndex])
  }

  function collapseFolders() {
    expandedShowKey = ""
    expandedSeasonKey = ""
  }

  function toggleFolder(item) {
    var key = String(item && item.ratingKey || "")
    if (!/^[0-9a-fA-F-]{8,48}$/.test(key)) return
    if (item.kind === "show") {
      if (expandedShowKey === key) {
        collapseFolders()
        return
      }
      expandedShowKey = key
      expandedSeasonKey = ""
      JellyCore.JellyfinState.loadFolderChildren(key, "seasons")
      return
    }
    if (item.kind === "season") {
      if (expandedSeasonKey === key) {
        expandedSeasonKey = ""
        return
      }
      expandedSeasonKey = key
      JellyCore.JellyfinState.loadFolderChildren(key, "episodes")
    }
  }

  function activateItem(item) {
    if (!item) return
    if (item.playable === false) {
      toggleFolder(item)
      return
    }
    JellyCore.JellyfinState.playItem(item, JellyCore.JellyfinState.playbackMode)
  }

  function toggleSelectedWatchState() {
    if (root.visibleItems.length > 0)
      JellyCore.JellyfinState.toggleWatchState(root.visibleItems[selectedIndex])
  }

  function setPlaybackMode(mode) {
    JellyCore.JellyfinState.setPlaybackMode(mode)
    keyCatcher.forceActiveFocus()
  }

  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var existing in root.settings)
      if (existing !== "id") entry[existing] = root.settings[existing]
    for (var key in values) entry[key] = values[key]

    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget) root.hostWidget.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function setShowNewItemCount(value) {
    root.persistSettings({ showNewItemCount: value === true })
  }

  function setAutoPlayNextEpisode(value) {
    root.persistSettings({ autoPlayNextEpisode: value === true })
  }

  function setSubtitleSearchLanguage(value) {
    var language = String(value || "").trim().toLowerCase()
    if (/^[a-z]{2}$/.test(language))
      root.persistSettings({ subtitleSearchLanguage: language })
  }

  onAutoPlayNextEpisodeChanged:
    JellyCore.JellyfinState.autoPlayNextEpisode = root.autoPlayNextEpisode

  onSubtitleSearchLanguageChanged:
    JellyCore.JellyfinState.subtitleSearchLanguage = root.subtitleSearchLanguage

  Component.onCompleted: {
    JellyCore.JellyfinState.autoPlayNextEpisode = root.autoPlayNextEpisode
    JellyCore.JellyfinState.subtitleSearchLanguage = root.subtitleSearchLanguage
  }

  function toggleWatched() {
    showWatched = !showWatched
    clampSelection()
    keyCatcher.forceActiveFocus()
  }

  function setView(view) {
    activeView = ["continue", "recent", "movies", "series"].indexOf(view) === -1 ? "continue" : view
    selectedIndex = 0
    cursorActive = true
    collapseFolders()
    Qt.callLater(function() {
      if (root.mediaSearchOpen) mediaSearchField.forceActiveFocus()
      else keyCatcher.forceActiveFocus()
    })
  }

  function cycleView(delta) {
    var views = ["continue", "recent", "movies", "series"]
    var index = views.indexOf(activeView)
    if (index < 0) index = 0
    setView(views[(index + delta + views.length) % views.length])
  }

  function summonBrowser() {
    if (!root.bar || !root.bar.shell || typeof root.bar.shell.summon !== "function") return
    root.controller.hide()
    root.bar.shell.summon(root.moduleName, JSON.stringify({
      view: root.activeView === "series" ? "series" : "movies"
    }))
  }

  function openMediaSearch() {
    if (settingsOpen) return
    helpOpen = false
    keybindingsOverlay.reset()
    mediaSearchOpen = true
    selectedIndex = 0
    Qt.callLater(function() { mediaSearchField.forceActiveFocus() })
  }

  function closeMediaSearch() {
    mediaSearchOpen = false
    mediaQuery = ""
    selectedIndex = 0
    clampSelection()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function openHelp() {
    mediaSearchOpen = false
    mediaQuery = ""
    helpOpen = true
    keybindingsOverlay.focusSearch()
  }

  function closeHelp() {
    helpOpen = false
    keybindingsOverlay.reset()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function toggleHelp() {
    if (helpOpen) closeHelp()
    else openHelp()
  }

  function openSettings() {
    helpOpen = false
    keybindingsOverlay.reset()
    mediaSearchOpen = false
    mediaQuery = ""
    settingsOverlay.open()
  }

  function closeSettings() {
    settingsOverlay.close()
    if (!settingsOverlay.opened)
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  onOpenedChanged: {
    if (opened) {
      root.cursorActive = true
      root.clampSelection()
      if (JellyCore.JellyfinState.initialized && !JellyCore.JellyfinState.configured)
        root.openSettings()
      else Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    } else {
      root.helpOpen = false
      keybindingsOverlay.reset()
      root.mediaSearchOpen = false
      root.mediaQuery = ""
      settingsOverlay.dismiss()
    }
  }

  Connections {
    target: JellyCore.JellyfinState
    function onItemsChanged() { root.clampSelection() }
    function onContinueItemsChanged() { root.clampSelection() }
    function onMovieItemsChanged() { root.clampSelection() }
    function onSeriesItemsChanged() { root.clampSelection() }
    function onFolderChildrenChanged() { root.clampSelection() }
    function onInitializedChanged() {
      if (root.opened && JellyCore.JellyfinState.initialized && !JellyCore.JellyfinState.configured)
        root.openSettings()
    }
    function onConfigurationFinished(success, detail) {
      settingsOverlay.finishConfiguration(success)
      if (success)
        Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    }
    function onConfiguredChanged() {
      settingsOverlay.syncServer()
    }
  }

  Component {
    id: jellyfinIcon
    Text {
      text: "󰟈"
      textFormat: Text.PlainText
      color: root.contentForeground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.display
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(430))
    contentHeight: panel.fittedContentHeight(
      root.settingsOpen ? settingsOverlay.contentImplicitHeight : panelColumn.implicitHeight,
      Style.space(760)
    )

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: keybindingsOverlay.inputFocused || mediaSearchField.activeFocus
        || settingsOverlay.inputFocused
      onMoveRequested: function(dx, dy) {
        if (!root.settingsOpen && !root.helpOpen) {
          if (dy !== 0) root.moveSelection(dy)
          else if (dx !== 0) root.switchPanel(dx)
        }
      }
      onActivateRequested: if (!root.settingsOpen && !root.helpOpen) root.playSelection()
      onDeleteRequested: if (!root.settingsOpen && !root.helpOpen) root.toggleSelectedWatchState()
      onCloseRequested: {
        if (root.helpOpen) root.closeHelp()
        else if (root.settingsOpen) root.closeSettings()
        else if (root.mediaSearchOpen) root.closeMediaSearch()
        else if (root.expandedSeasonKey !== "") root.expandedSeasonKey = ""
        else if (root.expandedShowKey !== "") root.collapseFolders()
        else root.close()
      }
      onTabRequested: function(direction) {
        if (!root.settingsOpen && !root.helpOpen) root.switchPanel(direction)
      }
      onTextKey: function(text) {
        if (root.settingsOpen) {
          return
        }
        if (root.helpOpen) {
          if (text === "?") root.closeHelp()
          else if (text === "/") keybindingsOverlay.focusSearch()
          return
        }
        if (text === "," || text === "<") root.cycleView(-1)
        else if (text === "." || text === ">") root.cycleView(1)
        else if (text === "j" || text === "J") root.moveSelection(1)
        else if (text === "k" || text === "K") root.moveSelection(-1)
        else if (text === "r" || text === "R") JellyCore.JellyfinState.refresh()
        else if (text === "u" || text === "U") JellyCore.JellyfinState.scanLibraries()
        else if (text === "w" || text === "W") root.setPlaybackMode("windowed")
        else if (text === "f" || text === "F") root.setPlaybackMode("fullscreen")
        else if (text === "[") root.cycleView(-1)
        else if (text === "]") root.cycleView(1)
        else if (text === "t" || text === "T") root.toggleWatched()
        else if (text === "c" || text === "C") root.setView("continue")
        else if (text === "a" || text === "A") root.setView("recent")
        else if (text === "m" || text === "M") root.setView("movies")
        else if (text === "s" || text === "S") root.setView("series")
        else if (text === "b" || text === "B") root.summonBrowser()
        else if (text === "p" || text === "P") JellyCore.JellyfinState.openJellyfinWeb()
        else if (text === "?") root.toggleHelp()
        else if (text === "/") root.openMediaSearch()
        else if ((text === "o" || text === "O") && root.visibleItems.length > 0)
          JellyCore.JellyfinState.openWebItem(root.visibleItems[root.selectedIndex])
      }

      Column {
        id: panelColumn
        visible: !root.helpOpen && !root.settingsOpen
        width: parent.width
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          iconComponent: jellyfinIcon
          title: "Jellyfin"
          meta: JellyCore.JellyfinState.safeText(
            JellyCore.JellyfinState.configured
              ? JellyCore.JellyfinState.freshnessText + " · " + root.sourceItems.length + " items"
              : "Jellyfin setup required",
            180
          )
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          trailingControl: Component {
            Row {
              spacing: Style.space(3)

              PanelActionButton {
                iconText: "\uEB4C" // cod-screen-full
                tooltipText: "Fullscreen playback (F)"
                foreground: JellyCore.JellyfinState.playbackMode === "fullscreen" ? Color.accent : root.contentForeground
                fontFamily: root.contentFontFamily
                bordered: JellyCore.JellyfinState.playbackMode === "fullscreen"
                enabled: !JellyCore.JellyfinState.playing
                onClicked: root.setPlaybackMode("fullscreen")
              }

              PanelActionButton {
                iconText: "\uEB4D" // cod-screen-normal
                tooltipText: "Windowed playback (W)"
                foreground: JellyCore.JellyfinState.playbackMode === "windowed" ? Color.accent : root.contentForeground
                fontFamily: root.contentFontFamily
                bordered: JellyCore.JellyfinState.playbackMode === "windowed"
                enabled: !JellyCore.JellyfinState.playing
                onClicked: root.setPlaybackMode("windowed")
              }

              PanelActionButton {
                iconText: "\uEB14" // cod-link-external
                tooltipText: JellyCore.JellyfinState.playingWindowed
                  ? "Bring player to this workspace"
                  : "No windowed player is active"
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                enabled: JellyCore.JellyfinState.playingWindowed
                  && !JellyCore.JellyfinState.movingPlayer
                onClicked: JellyCore.JellyfinState.bringPlayerHere()
              }

              PanelActionButton {
                iconText: "?"
                tooltipText: "Keybindings (?)"
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                onClicked: root.openHelp()
              }

              PanelActionButton {
                iconText: "\uEB37" // cod-refresh
                tooltipText: JellyCore.JellyfinState.scanning
                  ? "Scanning libraries…"
                  : "Scan all libraries (U)"
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                enabled: JellyCore.JellyfinState.configured && !JellyCore.JellyfinState.scanning
                onClicked: JellyCore.JellyfinState.scanLibraries()
              }
            }
          }
        }

        Text {
          visible: JellyCore.JellyfinState.lastError !== ""
          width: parent.width
          text: JellyCore.JellyfinState.safeText(JellyCore.JellyfinState.lastError, 220)
          textFormat: Text.PlainText
          color: root.urgentForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        PanelSeparator { foreground: root.contentForeground }

        Row {
          width: parent.width
          spacing: Style.space(5)

          Button {
            text: "Continue"
            fontSize: Style.font.caption
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            bordered: true
            active: root.activeView === "continue"
            onClicked: root.setView("continue")
          }

          Button {
            text: "Added"
            fontSize: Style.font.caption
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            bordered: true
            active: root.activeView === "recent"
            onClicked: root.setView("recent")
          }

          Button {
            text: "Movies"
            fontSize: Style.font.caption
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            bordered: true
            active: root.activeView === "movies"
            onClicked: root.setView("movies")
          }

          Button {
            text: "Shows"
            fontSize: Style.font.caption
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            bordered: true
            active: root.activeView === "series"
            onClicked: root.setView("series")
          }

          Item {
            width: Style.space(5)
            height: 1
          }

          Button {
            text: "Browse all"
            fontSize: Style.font.caption
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            bordered: true
            onClicked: root.summonBrowser()
          }
        }

        TextField {
          id: mediaSearchField
          visible: root.mediaSearchOpen
          width: parent.width
          text: root.mediaQuery
          maximumLength: 80
          placeholderText: "Search " + root.activeViewTitle.toLowerCase() + "…"
          foreground: root.contentForeground
          font.family: root.contentFontFamily
          onTextChanged: {
            root.mediaQuery = text
            root.selectedIndex = 0
            root.clampSelection()
          }
          Keys.onDownPressed: {
            keyCatcher.forceActiveFocus()
            root.moveSelection(1)
          }
          onAccepted: {
            keyCatcher.forceActiveFocus()
            root.playSelection()
          }
          Keys.onEscapePressed: root.closeMediaSearch()
        }

        Text {
          visible: JellyCore.JellyfinState.markMessage !== "" || JellyCore.JellyfinState.scanMessage !== ""
          width: parent.width
          text: JellyCore.JellyfinState.safeText(
            JellyCore.JellyfinState.markMessage !== ""
              ? JellyCore.JellyfinState.markMessage : JellyCore.JellyfinState.scanMessage,
            120
          )
          textFormat: Text.PlainText
          color: Color.accent
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: JellyCore.JellyfinState.playing
          width: parent.width
          text: "Playing " + JellyCore.JellyfinState.safeText(JellyCore.JellyfinState.playingTitle, 160)
            + " in " + JellyCore.JellyfinState.playbackMode + " mode"
          textFormat: Text.PlainText
          color: Color.accent
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
        }

        Item {
          width: parent.width
          implicitHeight: Math.max(
            listHeader.implicitHeight,
            sourceBadge.implicitHeight,
            jellyfinWebButton.implicitHeight,
            watchedVisibilityButton.implicitHeight
          )

          PanelSectionHeader {
            id: listHeader
            text: root.activeViewTitle
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Rectangle {
            id: sourceBadge
            width: sourceLabel.implicitWidth + Style.space(14)
            height: Style.space(22)
            anchors.right: jellyfinWebButton.left
            anchors.rightMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.cornerRadius
            color: JellyCore.JellyfinState.sourceState === "updated" ? Color.accent : "transparent"
            border.width: Math.max(1, Style.space(1))
            border.color: JellyCore.JellyfinState.sourceState === "updated" ? Color.accent : root.dimForeground

            Text {
              id: sourceLabel
              anchors.centerIn: parent
              text: JellyCore.JellyfinState.sourceLabel
              textFormat: Text.PlainText
              color: JellyCore.JellyfinState.sourceState === "updated" ? Color.background : root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            MouseArea {
              id: sourceBadgeMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.ArrowCursor
            }

            PanelToolTip {
              visible: sourceBadgeMouse.containsMouse
              text: JellyCore.JellyfinState.connectionName !== ""
                ? "Connected to " + JellyCore.JellyfinState.connectionName
                : "Connected to Jellyfin"
              fontFamily: root.contentFontFamily
            }
          }

          PanelActionButton {
            id: jellyfinWebButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰟈"
            tooltipText: "Open Jellyfin Web (P)"
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            size: Style.space(22)
            bordered: true
            enabled: JellyCore.JellyfinState.configured && !JellyCore.JellyfinState.openingWeb
            onClicked: JellyCore.JellyfinState.openJellyfinWeb()
          }

          PanelActionButton {
            id: watchedVisibilityButton
            visible: root.watchedCount > 0
            anchors.right: sourceBadge.left
            anchors.rightMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            iconText: root.showWatched ? "\uEAE7" : "\uEA70" // cod-eye-closed / cod-eye
            tooltipText: root.showWatched ? "Hide watched (T)" : "Show watched (T)"
            foreground: root.showWatched ? root.contentForeground : Color.accent
            fontFamily: root.contentFontFamily
            bordered: !root.showWatched
            onClicked: root.toggleWatched()
          }
        }

        Text {
          visible: !JellyCore.JellyfinState.initialized
          width: parent.width
          height: Style.space(56)
          text: "Reading saved Jellyfin data…"
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }

        Text {
          visible: JellyCore.JellyfinState.initialized && !JellyCore.JellyfinState.configured
          width: parent.width
          text: "Enter your Jellyfin server and sign in from Connection settings. Movie and show libraries are discovered automatically."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: JellyCore.JellyfinState.initialized && JellyCore.JellyfinState.configured
            && root.sourceItems.length === 0
          width: parent.width
          height: Style.space(56)
          text: JellyCore.JellyfinState.updating ? "Checking Jellyfin…" : "No items in this view"
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }


        Text {
          visible: JellyCore.JellyfinState.initialized && JellyCore.JellyfinState.configured
            && root.sourceItems.length > 0 && root.visibleItems.length === 0
          width: parent.width
          height: Style.space(56)
          text: root.mediaQuery.trim() !== ""
            ? "No matching media in this view" : "All items in this view are watched"
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }

        MediaList {
          id: mediaList
          width: parent.width
          height: Math.min(contentHeight, Style.space(root.mediaSearchOpen ? 365 : 410))
          items: root.visibleItems
          selectedIndex: root.selectedIndex
          cursorActive: root.cursorActive
          foreground: root.contentForeground
          dimForeground: root.dimForeground
          fontFamily: root.contentFontFamily
          onFocusRequested: function(index) { root.focusItem(index) }
          onPlayRequested: function(item) {
            root.activateItem(item)
          }
          onToggleWatchRequested: function(item) {
            JellyCore.JellyfinState.toggleWatchState(item)
          }
        }

        Item {
          width: parent.width
          implicitHeight: Math.max(footerKeys.implicitHeight, settingsButton.implicitHeight)

          Text {
            id: footerKeys
            anchors.left: parent.left
            anchors.right: settingsButton.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: ", . views · / find · J/K move · ↵ open · X toggle · B browse · ? keys"
            textFormat: Text.PlainText
            color: root.dimForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
          }

          PanelActionButton {
            id: settingsButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰒓"
            tooltipText: "Connection settings"
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            enabled: !JellyCore.JellyfinState.settingsBusy
            onClicked: root.openSettings()
          }
        }

      }

      KeybindingsOverlay {
        id: keybindingsOverlay
        visible: root.helpOpen
        anchors.fill: parent
        z: 20
        foreground: root.contentForeground
        dimForeground: root.dimForeground
        fontFamily: root.contentFontFamily
        onCloseRequested: root.closeHelp()
      }

      ConnectionSettings {
        id: settingsOverlay
        anchors.fill: parent
        z: 30
        foreground: root.contentForeground
        dimForeground: root.dimForeground
        urgentForeground: root.urgentForeground
        fontFamily: root.contentFontFamily
        iconComponent: jellyfinIcon
        showNewItemCount: root.showNewItemCount
        autoPlayNextEpisode: root.autoPlayNextEpisode
        subtitleSearchLanguage: root.subtitleSearchLanguage
        onShowNewItemCountRequested: function(value) { root.setShowNewItemCount(value) }
        onAutoPlayNextEpisodeRequested: function(value) {
          root.setAutoPlayNextEpisode(value)
        }
        onSubtitleSearchLanguageRequested: function(value) {
          root.setSubtitleSearchLanguage(value)
        }
        onDismissRequested: root.close()
      }
    }
  }
}
