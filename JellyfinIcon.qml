import QtQuick
import QtQuick.Shapes
import qs.Commons

Item {
  id: root

  property real iconSize: Style.bar.iconCanvas
  property color color: Color.foreground

  width: iconSize
  height: iconSize
  implicitWidth: iconSize
  implicitHeight: iconSize

  Behavior on color {
    ColorAnimation { duration: 160 }
  }

  Rectangle {
    anchors.fill: parent
    radius: Math.max(2, root.iconSize * 0.2)
    color: "transparent"
    border.width: Math.max(1, Math.round(root.iconSize * 0.1))
    border.color: root.color
  }

  Shape {
    anchors.fill: parent
    antialiasing: true

    ShapePath {
      fillColor: root.color
      strokeWidth: 0
      startX: root.width * 0.38
      startY: root.height * 0.28
      PathLine { x: root.width * 0.74; y: root.height * 0.5 }
      PathLine { x: root.width * 0.38; y: root.height * 0.72 }
    }
  }
}
