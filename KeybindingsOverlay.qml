import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "Model.js" as Model

Rectangle {
  id: root

  property color foreground: Color.foreground
  property color dimForeground: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property string query: ""
  property int selectedIndex: -1

  signal closeRequested()

  readonly property bool inputFocused: helpSearch.activeFocus
  readonly property var bindings: [
    { category: "Views & navigation", keys: "↑/↓ or J/K", action: "Move the selection cursor" },
    { category: "Views & navigation", keys: "Enter or Space", action: "Play the selected item, or open a show folder" },
    { category: "Views & navigation", keys: "←/→ or , / . or [ / ]", action: "Cycle Continue Watching, Added, Movies, Shows, and Downloads" },
    { category: "Views & navigation", keys: "Tab", action: "Switch Omarchy bar panels" },
    { category: "Views & navigation", keys: "T", action: "Show or hide watched items" },
    { category: "Views & navigation", keys: "C", action: "Show Continue Watching" },
    { category: "Views & navigation", keys: "A", action: "Show all recently added media" },
    { category: "Views & navigation", keys: "M", action: "Show recently added movies" },
    { category: "Views & navigation", keys: "S", action: "Show recently added shows" },
    { category: "Views & navigation", keys: "D", action: "Show the download list" },
    { category: "Views & navigation", keys: "B", action: "Open Browse All fullscreen" },
    { category: "Views & navigation", keys: "/", action: "Search the current compact media view" },
    { category: "Panel actions", keys: "?", action: "Toggle this keybindings list" },
    { category: "Panel actions", keys: "W", action: "Use a floating local player (when not using Jellyfin Web)" },
    { category: "Panel actions", keys: "F", action: "Use fullscreen local playback (when not using Jellyfin Web)" },
    { category: "Panel actions", keys: "O", action: "Open the item details in the Jellyfin webapp" },
    { category: "Panel actions", keys: "P", action: "Open Jellyfin Web as a standalone app" },
    { category: "Panel actions", keys: "Y", action: "Add the selected title to downloads, or remove it from the list" },
    { category: "Panel actions", keys: "X", action: "Toggle watched, or remove the selected download" },
    { category: "Panel actions", keys: "R", action: "Refresh Jellyfin activity and recently added media" },
    { category: "Panel actions", keys: "U", action: "Discover and scan all movie and show libraries" },
    { category: "Panel actions", keys: "Esc", action: "Collapse a folder, then close help or the panel" },
    { category: "Playback", keys: "Settings", action: "Jellyfin Web is the default player; enable Use local mpv player to opt out" },
    { category: "Browse All", keys: "J/K or ↑/↓", action: "Move the selection cursor" },
    { category: "Browse All", keys: "/", action: "Fuzzy-search the selected Movies or Shows scope" },
    { category: "Browse All", keys: "M/S/D", action: "Browse movies, shows, or downloads" },
    { category: "Browse All", keys: "Y", action: "Save the selected title, or remove it if it is already saved" },
    { category: "Browse All", keys: "X", action: "Remove the selected title from downloads" },
    { category: "Browse All", keys: "← / →", action: "Back (collapse folder or previous page) or forward (open folder or next page)" },
    { category: "Browse All", keys: "N/P", action: "Next or previous page" },
    { category: "Browse All", keys: "Esc", action: "Collapse a folder, then close Browse All" }
  ]
  readonly property var filteredBindings: filterBindings()
  readonly property var groupedBindings: groupBindings()

  color: Color.background

  function focusSearch() {
    Qt.callLater(function() { helpSearch.forceActiveFocus() })
  }

  function reset() {
    query = ""
    selectedIndex = -1
  }

  function firstBindingIndex() {
    var rows = groupedBindings
    for (var index = 0; index < rows.length; index++) {
      if (rows[index].kind === "binding") return index
    }
    return -1
  }

  function lastBindingIndex() {
    var rows = groupedBindings
    for (var index = rows.length - 1; index >= 0; index--) {
      if (rows[index].kind === "binding") return index
    }
    return -1
  }

  function moveSelection(delta) {
    var rows = groupedBindings
    if (rows.length === 0 || delta === 0) return
    if (selectedIndex < 0 || selectedIndex >= rows.length) {
      selectedIndex = delta > 0 ? firstBindingIndex() : lastBindingIndex()
    } else {
      var index = selectedIndex
      for (var step = 0; step < rows.length; step++) {
        index = (index + delta + rows.length) % rows.length
        if (rows[index].kind === "binding") {
          selectedIndex = index
          break
        }
      }
    }
    if (selectedIndex < 0) return
    Qt.callLater(function() {
      helpList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    })
  }

  function filterBindings() {
    var needle = String(query || "").trim().toLowerCase()
    if (needle === "") return bindings
    return bindings.filter(function(binding) {
      return (binding.category + " " + binding.keys + " " + binding.action)
        .toLowerCase().indexOf(needle) !== -1
    })
  }

  function groupBindings() {
    var rows = []
    var category = ""
    for (var index = 0; index < filteredBindings.length; index++) {
      var binding = filteredBindings[index]
      if (binding.category !== category) {
        category = binding.category
        rows.push({ kind: "header", category: category, keys: "", action: "" })
      }
      rows.push({
        kind: "binding",
        category: binding.category,
        keys: binding.keys,
        action: binding.action
      })
    }
    return rows
  }

  Column {
    anchors.fill: parent
    spacing: Style.space(10)

    Item {
      width: parent.width
      implicitHeight: Math.max(helpTitle.implicitHeight, closeHelpButton.implicitHeight)

      Text {
        id: helpTitle
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "Keybindings"
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }

      Button {
        id: closeHelpButton
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "Close  ?"
        fontSize: Style.font.caption
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.closeRequested()
      }
    }

    TextField {
      id: helpSearch
      width: parent.width
      text: root.query
      maximumLength: 80
      placeholderText: "Search keybindings…  /"
      foreground: root.foreground
      font.family: root.fontFamily
      onTextChanged: {
        root.query = text
        var rows = root.groupedBindings
        if (root.selectedIndex < 0 || root.selectedIndex >= rows.length
            || rows[root.selectedIndex].kind !== "binding")
          root.selectedIndex = -1
      }
      Keys.onEscapePressed: {
        if (text !== "") text = ""
        else root.closeRequested()
      }
      Keys.onDownPressed: {
        root.moveSelection(1)
        event.accepted = true
      }
      Keys.onUpPressed: {
        root.moveSelection(-1)
        event.accepted = true
      }
      Keys.onPressed: function(event) {
        if (event.text === "?") {
          root.closeRequested()
          event.accepted = true
        }
      }
    }

    Text {
      width: parent.width
      text: "Hover a shortcut, or press ↓, to scroll its description"
      textFormat: Text.PlainText
      color: root.dimForeground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    Text {
      visible: root.filteredBindings.length === 0
      width: parent.width
      text: "No matching keybindings"
      textFormat: Text.PlainText
      color: root.dimForeground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
    }

    ListView {
      id: helpList
      width: parent.width
      height: parent.height - y
      clip: true
      spacing: Style.space(4)
      model: root.groupedBindings
      currentIndex: root.selectedIndex
      boundsBehavior: Flickable.StopAtBounds

      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      delegate: Item {
        id: helpRow
        required property var modelData
        required property int index
        width: ListView.view.width
        implicitHeight: modelData.kind === "header"
          ? helpSectionHeader.implicitHeight + Style.space(8)
          : Math.max(bindingKey.implicitHeight, bindingAction.implicitHeight) + Style.space(14)

        PanelSectionHeader {
          id: helpSectionHeader
          visible: helpRow.modelData.kind === "header"
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.bottom: parent.bottom
          text: Model.plainText(helpRow.modelData.category, 40).toUpperCase()
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        CursorSurface {
          visible: helpRow.modelData.kind === "binding"
          anchors.fill: parent
          foreground: root.foreground
          hasCursor: root.selectedIndex === helpRow.index

          MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onEntered: root.selectedIndex = helpRow.index
          }

          Text {
            id: bindingKey
            width: Style.space(100)
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            text: Model.plainText(helpRow.modelData.keys, 40)
            textFormat: Text.PlainText
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }

          MarqueeLabel {
            id: bindingAction
            anchors.left: bindingKey.right
            anchors.right: parent.right
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            text: Model.plainText(helpRow.modelData.action, 160)
            color: root.foreground
            fontFamily: root.fontFamily
            fontPixelSize: Style.font.bodySmall
            scrolling: root.selectedIndex === helpRow.index
          }
        }
      }
    }
  }
}
