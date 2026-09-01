import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "." as JellyCore

BarWidget {
  id: root
  moduleName: "io.github.hopelezz.omajelly"

  readonly property color jellyfinBlue: "#00A4DC"
  readonly property bool showNewItemCount: setting("showNewItemCount", true) !== false
  readonly property bool useJellyfinBlueForNewItems:
    setting("useJellyfinBlueForNewItems", false) === true
  readonly property bool hasNewItems: JellyCore.JellyfinState.newCount > 0
  readonly property bool showBadge: !root.vertical && root.showNewItemCount && root.hasNewItems
  readonly property color iconColor: {
    if (root.hasNewItems && root.useJellyfinBlueForNewItems) return root.jellyfinBlue
    if (root.hasNewItems) return root.bar ? root.bar.urgent : Color.urgent
    return root.bar ? root.bar.barForeground : Color.foreground
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true
    : false

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function handlePress(buttonCode) {
    if (buttonCode === Qt.MiddleButton) JellyCore.JellyfinState.refresh()
    else if (buttonCode === Qt.RightButton) {
      var panel = panelLoader.item
      if (panel && panel.opened && panel.settingsOpen === true)
        panel.close()
      else {
        JellyCore.JellyfinState.settingsRequested = true
        root.open()
      }
    }
    else root.toggle()
  }

  implicitWidth: contents.implicitWidth
  implicitHeight: contents.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Row {
    id: contents
    spacing: Style.space(3)

    BarIconButton {
      id: button
      bar: root.bar
      active: root.hasNewItems
      useActiveColor: true
      activeColor: root.iconColor
      tooltipText: JellyCore.JellyfinState.tooltipText
      iconComponent: jellyfinMark
      onPressed: function(buttonCode) { root.handlePress(buttonCode) }
    }

    Text {
      id: countLabel
      visible: root.showBadge
      text: String(JellyCore.JellyfinState.newCount)
      textFormat: Text.PlainText
      color: root.iconColor
      font.family: button.fontFamily
      font.pixelSize: button.fontSize
      font.bold: true
      anchors.verticalCenter: parent.verticalCenter

      Behavior on color {
        enabled: !root.bar || root.bar.foregroundAnimationEnabled
        ColorAnimation { duration: 160 }
      }

      MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) { root.handlePress(mouse.button) }
      }
    }
  }

  Component {
    id: jellyfinMark
    Item {
      JellyfinIcon {
        anchors.centerIn: parent
        iconSize: Style.bar.iconCanvas
        color: root.iconColor
      }
    }
  }
}
