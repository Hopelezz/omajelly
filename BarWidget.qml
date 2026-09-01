import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "." as JellyCore

BarWidget {
  id: root
  moduleName: "io.github.hopelezz.omajelly"

  readonly property bool showNewItemCount: setting("showNewItemCount", true) !== false
  readonly property bool hasNewItems: JellyCore.JellyfinState.newCount > 0
  readonly property bool showBadge: !root.vertical && root.showNewItemCount && root.hasNewItems
  readonly property string jellyfinGlyph: "󰟈"

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

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

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

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.showBadge
      ? root.jellyfinGlyph + " " + String(JellyCore.JellyfinState.newCount)
      : root.jellyfinGlyph
    slotSize: Style.bar.iconSlot * (root.showBadge ? 2 : 1)
    tooltipText: JellyCore.JellyfinState.tooltipText
    onPressed: function(buttonCode) {
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
  }
}
