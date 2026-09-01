import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "." as JellyCore
import "Model.js" as Model

ListView {
  id: root

  property var items: []
  property int selectedIndex: 0
  property bool cursorActive: true
  property color foreground: Color.foreground
  property color dimForeground: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family

  signal focusRequested(int index)
  signal playRequested(var item)
  signal toggleWatchRequested(var item)

  visible: items.length > 0
  clip: true
  spacing: Style.space(3)
  model: items
  currentIndex: selectedIndex
  boundsBehavior: Flickable.StopAtBounds
  interactive: contentHeight > height
  reuseItems: true

  ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

  delegate: CursorSurface {
    id: mediaRow
    required property var modelData
    required property int index
    width: root.width
    implicitHeight: Style.space(58)
    foreground: root.foreground
    hasCursor: root.cursorActive && root.selectedIndex === index

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.focusRequested(mediaRow.index)
      onClicked: {
        root.focusRequested(mediaRow.index)
        root.playRequested(mediaRow.modelData)
      }
    }

    Text {
      id: kindIcon
      width: Style.space(24)
      anchors.left: parent.left
      anchors.leftMargin: Style.space(10) + (mediaRow.modelData.depth || 0) * Style.space(16)
      anchors.verticalCenter: parent.verticalCenter
      text: Model.itemIcon(mediaRow.modelData)
      textFormat: Text.PlainText
      color: mediaRow.modelData.isNew ? Color.accent : root.dimForeground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      horizontalAlignment: Text.AlignHCenter
    }

    Column {
      anchors.left: kindIcon.right
      anchors.leftMargin: Style.space(8)
      anchors.right: watchBadge.left
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(1)

      Text {
        width: parent.width
        text: Model.plainText(mediaRow.modelData.title, 256)
        textFormat: Text.PlainText
        color: mediaRow.modelData.watchState === "watched"
          ? root.dimForeground : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: mediaRow.modelData.watchState !== "watched"
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: Model.plainText(mediaRow.modelData.subtitle, 256)
          + (mediaRow.modelData.addedLabel === ""
            ? "" : " · " + Model.plainText(mediaRow.modelData.addedLabel, 80))
          + (mediaRow.modelData.playbackHint === ""
            ? "" : " · " + Model.plainText(mediaRow.modelData.playbackHint, 80))
        textFormat: Text.PlainText
        color: root.dimForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Button {
      id: watchBadge
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      z: 1
      text: mediaRow.modelData.playable === false
        ? (mediaRow.modelData.kind === "season" || mediaRow.modelData.kind === "show"
          ? "OPEN" : Model.watchLabel(mediaRow.modelData.watchState))
        : Model.watchLabel(mediaRow.modelData.watchState)
      tooltipText: mediaRow.modelData.playable === false
        ? "Open folder"
        : (mediaRow.modelData.watchState === "watched" ? "Mark unwatched" : "Mark watched")
      fontSize: Style.font.caption
      foreground: mediaRow.modelData.isNew ? Color.accent : root.dimForeground
      fontFamily: root.fontFamily
      horizontalPadding: Style.space(6)
      verticalPadding: Style.space(2)
      bordered: true
      active: JellyCore.JellyfinState.markingRatingKey === String(mediaRow.modelData.ratingKey)
      enabled: mediaRow.modelData.playable === false || !JellyCore.JellyfinState.updating
      onHovered: function(isHovered) {
        if (isHovered) root.focusRequested(mediaRow.index)
      }
      onClicked: {
        root.focusRequested(mediaRow.index)
        if (mediaRow.modelData.playable === false) {
          root.playRequested(mediaRow.modelData)
          return
        }
        root.toggleWatchRequested(mediaRow.modelData)
      }
    }
  }
}
