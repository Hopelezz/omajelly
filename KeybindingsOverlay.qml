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

  signal closeRequested()

  readonly property bool inputFocused: helpSearch.activeFocus
  readonly property var bindings: [
    { category: "Views & navigation", keys: "↑/↓ or J/K", action: "Move the selection cursor" },
    { category: "Views & navigation", keys: "Enter", action: "Play the selected item, or open a show folder" },
    { category: "Views & navigation", keys: ", / .", action: "Cycle Continue Watching, Added, Movies, and Shows" },
    { category: "Views & navigation", keys: "T", action: "Show or hide watched items" },
    { category: "Views & navigation", keys: "C", action: "Show Continue Watching" },
    { category: "Views & navigation", keys: "A", action: "Show all recently added media" },
    { category: "Views & navigation", keys: "M", action: "Show recently added movies" },
    { category: "Views & navigation", keys: "S", action: "Show recently added shows" },
    { category: "Views & navigation", keys: "B", action: "Open Browse All fullscreen" },
    { category: "Views & navigation", keys: "/", action: "Search the current compact media view" },
    { category: "Panel actions", keys: "?", action: "Toggle this keybindings list" },
    { category: "Panel actions", keys: "W", action: "Use a floating window" },
    { category: "Panel actions", keys: "F", action: "Use fullscreen playback" },
    { category: "Panel actions", keys: "O", action: "Open the item in Jellyfin Web" },
    { category: "Panel actions", keys: "P", action: "Open Jellyfin Web" },
    { category: "Panel actions", keys: "X", action: "Toggle selected item watched or unwatched" },
    { category: "Panel actions", keys: "R", action: "Refresh Jellyfin activity and recently added media" },
    { category: "Panel actions", keys: "U", action: "Discover and scan all movie and show libraries" },
    { category: "Panel actions", keys: "Esc", action: "Close help or the panel" },
    { category: "Playback", keys: "Mouse", action: "Show mpv playback controls" },
    { category: "Playback", keys: "Space", action: "Pause or resume" },
    { category: "Playback", keys: "←/→", action: "Seek backward or forward" },
    { category: "Playback", keys: "↑/↓", action: "Raise or lower volume" },
    { category: "Playback", keys: "M", action: "Mute or unmute" },
    { category: "Playback", keys: "#", action: "Cycle audio streams" },
    { category: "Playback", keys: "J", action: "Cycle subtitle streams" },
    { category: "Playback", keys: "Ctrl+J", action: "Search Jellyfin subtitles" },
    { category: "Playback", keys: "F", action: "Toggle player fullscreen" },
    { category: "Playback", keys: "Q", action: "Quit the player" },
    { category: "Browse All", keys: "J/K or ↑/↓", action: "Move the selection cursor" },
    { category: "Browse All", keys: "/", action: "Fuzzy-search the selected Movies or Shows scope" },
    { category: "Browse All", keys: "M/S", action: "Browse movies or shows" },
    { category: "Browse All", keys: ", / .", action: "Back (collapse folder or previous page) or forward (open folder or next page)" },
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
      onTextChanged: root.query = text
      Keys.onEscapePressed: {
        if (text !== "") text = ""
        else root.closeRequested()
      }
      Keys.onPressed: function(event) {
        if (event.text === "?") {
          root.closeRequested()
          event.accepted = true
        }
      }
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
      width: parent.width
      height: parent.height - y
      clip: true
      spacing: Style.space(4)
      model: root.groupedBindings
      boundsBehavior: Flickable.StopAtBounds

      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      delegate: Item {
        id: helpRow
        required property var modelData
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

        Rectangle {
          visible: helpRow.modelData.kind === "binding"
          anchors.fill: parent
          radius: Style.cornerRadius
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.05)

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

          Text {
            id: bindingAction
            anchors.left: bindingKey.right
            anchors.right: parent.right
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            text: Model.plainText(helpRow.modelData.action, 120)
            textFormat: Text.PlainText
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }
        }
      }
    }
  }
}
