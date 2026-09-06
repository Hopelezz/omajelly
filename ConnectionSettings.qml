import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "." as JellyCore

Rectangle {
  id: root

  property bool opened: false
  property bool confirmClear: false
  property bool tokenExpanded: false
  property string settingsPage: "account"
  property color foreground: Color.foreground
  property color dimForeground: Qt.darker(foreground, 1.55)
  property color urgentForeground: Color.urgent
  property string fontFamily: Style.font.family
  property Component iconComponent
  property bool showNewItemCount: true
  property bool useLocalPlayer: false

  signal dismissRequested()
  signal showNewItemCountRequested(bool value)
  signal playInBrowserRequested(bool value)

  readonly property bool pairing: JellyCore.JellyfinState.authenticationState === "starting"
    || JellyCore.JellyfinState.authenticationState === "waiting"
  readonly property bool pagesEnabled: JellyCore.JellyfinState.configured
  readonly property string activePage: pagesEnabled ? settingsPage : "account"
  readonly property bool inputFocused: serverField.activeFocus || usernameField.activeFocus
    || passwordField.activeFocus || tokenField.activeFocus
    || saveSettingsButton.activeFocus || closeSettingsButton.activeFocus
    || clearSettingsButton.activeFocus || newItemCountToggle.activeFocus
    || playInBrowserToggle.activeFocus
    || advancedButton.activeFocus
    || quickConnectButton.activeFocus || cancelQuickConnectButton.activeFocus
    || pageGroup.activeFocus || limitGroup.activeFocus
  readonly property real contentImplicitHeight: settingsColumn.implicitHeight
  readonly property int selectedLimitGib: {
    var bytes = JellyCore.JellyfinState.downloadMaxBytes
    var gib = Math.round(bytes / (1024 * 1024 * 1024))
    if ([5, 10, 20, 40].indexOf(gib) === -1) return 20
    return gib
  }

  function formattedQuickConnectCode() {
    var code = JellyCore.JellyfinState.quickConnectCode
    if (code.length === 6) return code.slice(0, 3) + "  " + code.slice(3)
    if (code.length === 8) return code.slice(0, 4) + "  " + code.slice(4)
    return code
  }

  function cacheUsageText() {
    function gigabytes(bytes) {
      var value = Number(bytes) / (1024 * 1024 * 1024)
      if (value <= 0) return "0"
      if (value < 0.1) return value.toFixed(2)
      return String(Math.round(value * 10) / 10)
    }
    return "Using " + gigabytes(JellyCore.JellyfinState.downloadUsedBytes)
      + " GB of " + gigabytes(JellyCore.JellyfinState.downloadMaxBytes || 20 * 1024 * 1024 * 1024)
      + " GB"
  }

  function setPage(page) {
    var pages = ["account", "player", "downloads", "bar"]
    settingsPage = pages.indexOf(page) === -1 ? "account" : page
    confirmClear = false
  }

  visible: opened
  color: Color.background

  function open() {
    confirmClear = false
    opened = true
    tokenExpanded = false
    settingsPage = "account"
    serverField.text = JellyCore.JellyfinState.connectionServer
    usernameField.text = ""
    passwordField.text = ""
    tokenField.text = ""
    JellyCore.JellyfinState.loadDownloads()
    Qt.callLater(function() { serverField.forceActiveFocus() })
  }

  function close() {
    if (JellyCore.JellyfinState.authenticationState !== "idle") {
      JellyCore.JellyfinState.cancelQuickConnect()
      return
    }
    if (!JellyCore.JellyfinState.configured) {
      dismissRequested()
      return
    }
    dismiss()
  }

  function dismiss() {
    opened = false
    confirmClear = false
    passwordField.text = ""
    tokenField.text = ""
    tokenExpanded = false
  }

  function submit() {
    var submitted = JellyCore.JellyfinState.configure({
      server: serverField.text,
      username: usernameField.text,
      password: passwordField.text,
      token: tokenField.text
    })
    if (submitted) {
      passwordField.text = ""
      tokenField.text = ""
    }
  }

  function finishConfiguration(success) {
    if (!success) return
    opened = false
    confirmClear = false
  }

  function syncServer() {
    if (opened)
      serverField.text = JellyCore.JellyfinState.connectionServer
  }

  function librarySummary() {
    var movies = JellyCore.JellyfinState.movieLibraries
    var series = JellyCore.JellyfinState.seriesLibraries
    var movieNames = movies.map(function(item) { return item.title || "Library " + item.id })
    var seriesNames = series.map(function(item) { return item.title || "Library " + item.id })
    var lines = []
    if (movieNames.length) lines.push("Movies · " + movieNames.join(", "))
    if (seriesNames.length) lines.push("Shows · " + seriesNames.join(", "))
    return lines.length ? lines.join("\n") : "Libraries are discovered when the connection is tested."
  }

  Flickable {
    anchors.fill: parent
    contentWidth: width
    contentHeight: settingsColumn.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    interactive: contentHeight > height

    Column {
      id: settingsColumn
      width: parent.width
      spacing: Style.space(10)

      PanelHero {
        width: parent.width
        iconComponent: root.iconComponent
        title: "Jellyfin"
        meta: JellyCore.JellyfinState.configured ? "Settings" : "Connect to Jellyfin"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      PanelSeparator { foreground: root.foreground }

      ButtonGroup {
        id: pageGroup
        visible: root.pagesEnabled && !root.pairing
        width: parent.width
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        value: root.activePage
        options: [
          { value: "account", label: "Account" },
          { value: "player", label: "Player" },
          { value: "downloads", label: "Downloads" },
          { value: "bar", label: "Bar" }
        ]
        onChanged: function(value) { root.setPage(value) }
      }

      Text {
        visible: JellyCore.JellyfinState.lastError !== ""
        width: parent.width
        text: JellyCore.JellyfinState.safeText(JellyCore.JellyfinState.lastError, 220)
        textFormat: Text.PlainText
        color: root.urgentForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Text {
        visible: JellyCore.JellyfinState.setupMessage !== ""
        width: parent.width
        text: JellyCore.JellyfinState.safeText(JellyCore.JellyfinState.setupMessage, 220)
        textFormat: Text.PlainText
        color: Color.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Column {
        visible: root.activePage === "account"
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "SERVER"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Text {
          visible: JellyCore.JellyfinState.configured
          width: parent.width
          text: (JellyCore.JellyfinState.authenticationMode === "quickconnect"
            ? "Signed in with Quick Connect"
            : (JellyCore.JellyfinState.authenticationMode === "password"
              ? "Signed in with username" : "API key connection"))
            + " · " + (JellyCore.JellyfinState.connectionName
              || JellyCore.JellyfinState.connectionServer)
          textFormat: Text.PlainText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          visible: JellyCore.JellyfinState.configured
          width: parent.width
          text: root.librarySummary()
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        TextField {
          id: serverField
          width: parent.width
          placeholderText: "http://media/jellyfin"
          maximumLength: 512
          foreground: root.foreground
          font.family: root.fontFamily
          enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
          inputMethodHints: Qt.ImhUrlCharactersOnly
          onAccepted: JellyCore.JellyfinState.startQuickConnect(serverField.text)
          Keys.onEscapePressed: root.close()
        }

        Text {
          width: parent.width
          text: "Use the Jellyfin base URL, including a reverse-proxy path if you have one."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Button {
          id: quickConnectButton
          width: parent.width
          text: JellyCore.JellyfinState.authenticationState === "starting"
            ? "Getting a code…"
            : (JellyCore.JellyfinState.authenticationState === "waiting"
              ? "Waiting for a signed-in app…"
              : (JellyCore.JellyfinState.authenticationMode === "quickconnect"
                ? "Get a new Quick Connect code" : "Get a Quick Connect code"))
          iconText: root.pairing ? "󰑐" : ""
          iconSpinning: root.pairing
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          focusable: true
          enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
          onClicked: JellyCore.JellyfinState.startQuickConnect(serverField.text)
          Keys.onEscapePressed: root.close()
        }

        Text {
          visible: JellyCore.JellyfinState.quickConnectCode !== ""
          width: parent.width
          text: root.formattedQuickConnectCode()
          textFormat: Text.PlainText
          color: Color.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.display
          font.bold: true
          font.letterSpacing: Style.space(1)
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          width: parent.width
          text: root.pairing
            ? "On a signed-in Jellyfin app, open the profile menu → Quick Connect and enter the code."
            : "Creates a short code. Enter it in a Jellyfin app that is already signed in."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Button {
          id: cancelQuickConnectButton
          visible: root.pairing
          width: parent.width
          text: "Cancel code"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          focusable: true
          enabled: true
          onClicked: JellyCore.JellyfinState.cancelQuickConnect()
          Keys.onEscapePressed: root.close()
        }

        Column {
          visible: JellyCore.JellyfinState.configured && !root.pairing
          width: parent.width
          spacing: Style.space(10)

          PanelSectionHeader {
            width: parent.width
            text: "PASSWORD SIGN-IN"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          TextField {
            id: usernameField
            width: parent.width
            placeholderText: "Jellyfin username"
            maximumLength: 128
            foreground: root.foreground
            font.family: root.fontFamily
            enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
            onAccepted: passwordField.forceActiveFocus()
            Keys.onEscapePressed: root.close()
          }

          TextField {
            id: passwordField
            width: parent.width
            placeholderText: JellyCore.JellyfinState.configured
              ? "Leave blank to keep the saved token" : "Jellyfin password"
            echoMode: TextInput.Password
            maximumLength: 256
            foreground: root.foreground
            font.family: root.fontFamily
            enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
            onAccepted: root.submit()
            Keys.onEscapePressed: root.close()
          }

          Button {
            id: saveSettingsButton
            width: parent.width
            text: JellyCore.JellyfinState.configuring ? "Testing connection…" : "Test and save connection"
            iconText: JellyCore.JellyfinState.configuring ? "󰑐" : ""
            iconSpinning: JellyCore.JellyfinState.configuring
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            focusable: true
            enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
            onClicked: root.submit()
          }

          Button {
            id: advancedButton
            width: parent.width
            text: root.tokenExpanded ? "Hide API key" : "Use an API key instead"
            foreground: root.dimForeground
            fontFamily: root.fontFamily
            bordered: false
            focusable: true
            enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
            onClicked: {
              root.tokenExpanded = !root.tokenExpanded
              if (root.tokenExpanded) Qt.callLater(function() { tokenField.forceActiveFocus() })
            }
            Keys.onEscapePressed: root.close()
          }

          Column {
            visible: root.tokenExpanded
            width: parent.width
            spacing: Style.space(8)

            TextField {
              id: tokenField
              width: parent.width
              placeholderText: JellyCore.JellyfinState.configured
                ? "Leave blank to keep the saved token" : "Dashboard → API Keys"
              echoMode: TextInput.Password
              maximumLength: 8192
              foreground: root.foreground
              font.family: root.fontFamily
              enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
              onAccepted: root.submit()
              Keys.onEscapePressed: root.close()
            }

            Text {
              width: parent.width
              text: "Create a dedicated key so this machine can be revoked on its own."
              textFormat: Text.PlainText
              color: root.dimForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          Text {
            width: parent.width
            text: "Passwords and API keys go to the helper over stdin and the desktop secret service. They are never written to plugin settings, command lines, logs, or cache."
            textFormat: Text.PlainText
            color: root.dimForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Column {
        visible: root.activePage === "player"
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "PLAYBACK"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Toggle {
          id: playInBrowserToggle
          width: parent.width
          label: "Use local mpv player"
          description: "Jellyfin Web is the default. Turn this on only to play streams with mpv instead."
          checked: root.useLocalPlayer
          enabled: JellyCore.JellyfinState.configured
            && !JellyCore.JellyfinState.settingsBusy
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.playInBrowserRequested(!root.useLocalPlayer)
          Keys.onEscapePressed: root.close()
        }
      }

      Column {
        visible: root.activePage === "downloads"
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "CACHE SIZE"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          text: root.cacheUsageText()
          textFormat: Text.PlainText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        ButtonGroup {
          id: limitGroup
          width: parent.width
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          value: String(root.selectedLimitGib)
          enabled: !JellyCore.JellyfinState.settingDownloadLimit
          options: [
            { value: "5", label: "5 GB" },
            { value: "10", label: "10 GB" },
            { value: "20", label: "20 GB" },
            { value: "40", label: "40 GB" }
          ]
          onChanged: function(value) {
            JellyCore.JellyfinState.setDownloadLimit(Number(value))
          }
        }

        Text {
          width: parent.width
          text: "Y saves a title. Ready titles play from disk. Lowering the limit deletes the oldest ready files first."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }

      Column {
        visible: root.activePage === "bar"
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "BAR"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Toggle {
          id: newItemCountToggle
          width: parent.width
          label: "Show new-item count"
          description: "Show the count to the right of the Jellyfin icon."
          checked: root.showNewItemCount
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.showNewItemCountRequested(!root.showNewItemCount)
          Keys.onEscapePressed: root.close()
        }
      }

      Row {
        width: parent.width
        spacing: Style.space(5)

        Button {
          id: closeSettingsButton
          width: JellyCore.JellyfinState.configured
            ? (parent.width - parent.spacing) / 2 : parent.width
          text: "Close"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          focusable: true
          enabled: !JellyCore.JellyfinState.configuring
          onClicked: root.close()
        }

        Button {
          id: clearSettingsButton
          visible: JellyCore.JellyfinState.configured
          width: (parent.width - parent.spacing) / 2
          text: root.confirmClear ? "Confirm remove" : "Remove credentials"
          foreground: root.confirmClear ? root.urgentForeground : root.foreground
          fontFamily: root.fontFamily
          bordered: true
          focusable: true
          enabled: !JellyCore.JellyfinState.updating && !JellyCore.JellyfinState.authenticating
          onClicked: {
            if (root.confirmClear) {
              if (JellyCore.JellyfinState.clearConfiguration()) root.confirmClear = false
            } else root.confirmClear = true
          }
        }
      }
    }
  }
}
