import QtQuick
import qs.Commons

Item {
  id: root

  property string text: ""
  property color color: "white"
  property string fontFamily: Style.font.family
  property int fontPixelSize: Style.font.body
  property bool fontBold: false
  property bool scrolling: false

  clip: true
  implicitHeight: measure.implicitHeight

  readonly property bool overflowing: measure.implicitWidth > root.width + 1
  readonly property int gap: Math.max(24, Style.space(32))
  readonly property bool running: scrolling && overflowing && root.width > 0

  Text {
    id: measure
    visible: false
    text: root.text
    textFormat: Text.PlainText
    font.family: root.fontFamily
    font.pixelSize: root.fontPixelSize
    font.bold: root.fontBold
  }

  Text {
    id: clipped
    visible: !root.running
    width: root.width
    text: root.text
    textFormat: Text.PlainText
    color: root.color
    font.family: root.fontFamily
    font.pixelSize: root.fontPixelSize
    font.bold: root.fontBold
    elide: Text.ElideRight
  }

  Item {
    id: track
    visible: root.running
    height: parent.height
    width: measure.implicitWidth * 2 + root.gap

    Text {
      id: primary
      text: root.text
      textFormat: Text.PlainText
      color: root.color
      font.family: root.fontFamily
      font.pixelSize: root.fontPixelSize
      font.bold: root.fontBold
    }

    Text {
      x: measure.implicitWidth + root.gap
      text: root.text
      textFormat: Text.PlainText
      color: root.color
      font.family: root.fontFamily
      font.pixelSize: root.fontPixelSize
      font.bold: root.fontBold
    }
  }

  SequentialAnimation {
    id: marquee
    loops: Animation.Infinite
    running: root.running

    PauseAnimation { duration: 1000 }

    NumberAnimation {
      target: track
      property: "x"
      from: 0
      to: -(measure.implicitWidth + root.gap)
      duration: Math.max(3500, Math.round((measure.implicitWidth + root.gap) * 22))
      easing.type: Easing.Linear
    }

    PauseAnimation { duration: 800 }
  }

  onRunningChanged: {
    if (!running) {
      marquee.stop()
      track.x = 0
    }
  }

  onTextChanged: {
    track.x = 0
    if (running) marquee.restart()
  }

  onWidthChanged: {
    if (!running) track.x = 0
  }
}
