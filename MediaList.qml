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
  signal removeRequested(var item)

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
      id: rowMouse
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

      MarqueeLabel {
        width: parent.width
        text: Model.plainText(mediaRow.modelData.title, 256)
        color: mediaRow.modelData.watchState === "watched"
          ? root.dimForeground : root.foreground
        fontFamily: root.fontFamily
        fontPixelSize: Style.font.body
        fontBold: mediaRow.modelData.watchState !== "watched"
        scrolling: mediaRow.hasCursor || rowMouse.containsMouse
      }

      Text {
        width: parent.width
        text: {
          var parts = [Model.plainText(mediaRow.modelData.subtitle, 256)]
          if (mediaRow.modelData.downloadState) {
            if (mediaRow.modelData.playbackHint !== "")
              parts.push(Model.plainText(mediaRow.modelData.playbackHint, 80))
          } else {
            if (mediaRow.modelData.addedLabel !== "")
              parts.push(Model.plainText(mediaRow.modelData.addedLabel, 80))
            if (mediaRow.modelData.playbackHint !== ""
                && mediaRow.modelData.playbackHint !== mediaRow.modelData.addedLabel)
              parts.push(Model.plainText(mediaRow.modelData.playbackHint, 80))
          }
          return parts.filter(function(part) { return part !== "" }).join(" · ")
        }
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
      text: mediaRow.modelData.downloadState
        ? "REMOVE"
        : (mediaRow.modelData.playable === false
          ? (mediaRow.modelData.kind === "season" || mediaRow.modelData.kind === "show"
            ? "OPEN" : Model.watchLabel(mediaRow.modelData.watchState))
          : Model.watchLabel(mediaRow.modelData.watchState))
      tooltipText: mediaRow.modelData.downloadState
        ? "Remove from the download list"
        : (mediaRow.modelData.playable === false
          ? "Open folder"
          : (mediaRow.modelData.watchState === "watched" ? "Mark unwatched" : "Mark watched"))
      fontSize: Style.font.caption
      foreground: mediaRow.modelData.isNew ? Color.accent : root.dimForeground
      fontFamily: root.fontFamily
      horizontalPadding: Style.space(6)
      verticalPadding: Style.space(2)
      bordered: true
      active: mediaRow.modelData.downloadState
        ? JellyCore.JellyfinState.removingDownload
        : JellyCore.JellyfinState.markingRatingKey === String(mediaRow.modelData.ratingKey)
      enabled: mediaRow.modelData.downloadState
        ? !JellyCore.JellyfinState.removingDownload
        : (mediaRow.modelData.playable === false || !JellyCore.JellyfinState.updating)
      onHovered: function(isHovered) {
        if (isHovered) root.focusRequested(mediaRow.index)
      }
      onClicked: {
        root.focusRequested(mediaRow.index)
        if (mediaRow.modelData.downloadState) {
          root.removeRequested(mediaRow.modelData)
          return
        }
        if (mediaRow.modelData.playable === false) {
          root.playRequested(mediaRow.modelData)
          return
        }
        root.toggleWatchRequested(mediaRow.modelData)
      }
    }
  }
}
