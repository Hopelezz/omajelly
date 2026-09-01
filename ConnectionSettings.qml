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
  property color foreground: Color.foreground
  property color dimForeground: Qt.darker(foreground, 1.55)
  property color urgentForeground: Color.urgent
  property string fontFamily: Style.font.family
  property Component iconComponent
  property bool showNewItemCount: true
  property bool useJellyfinBlueForNewItems: true
  property bool autoPlayNextEpisode: false
  property string subtitleSearchLanguage: "en"

  signal dismissRequested()
  signal showNewItemCountRequested(bool value)
  signal useJellyfinBlueForNewItemsRequested(bool value)
  signal autoPlayNextEpisodeRequested(bool value)
  signal subtitleSearchLanguageRequested(string value)

  readonly property bool pairing: JellyCore.JellyfinState.authenticationState === "starting"
    || JellyCore.JellyfinState.authenticationState === "waiting"
  readonly property bool inputFocused: serverField.activeFocus || usernameField.activeFocus
    || passwordField.activeFocus || tokenField.activeFocus
    || saveSettingsButton.activeFocus || closeSettingsButton.activeFocus
    || clearSettingsButton.activeFocus || newItemCountToggle.activeFocus
    || jellyfinBlueToggle.activeFocus || autoPlayNextToggle.activeFocus
    || subtitleLanguageField.activeFocus || advancedButton.activeFocus
    || quickConnectButton.activeFocus || cancelQuickConnectButton.activeFocus
  readonly property real contentImplicitHeight: settingsColumn.implicitHeight

  function formattedQuickConnectCode() {
    var code = JellyCore.JellyfinState.quickConnectCode
    if (code.length === 6) return code.slice(0, 3) + "  " + code.slice(3)
    if (code.length === 8) return code.slice(0, 4) + "  " + code.slice(4)
    return code
  }

  visible: opened
  color: Color.background

  function open() {
    confirmClear = false
    opened = true
    tokenExpanded = false
    serverField.text = JellyCore.JellyfinState.connectionServer
    usernameField.text = ""
    passwordField.text = ""
    tokenField.text = ""
    subtitleLanguageField.text = root.subtitleSearchLanguage
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

  function commitSubtitleLanguage() {
    var language = subtitleLanguageField.text.trim().toLowerCase()
    if (/^[a-z]{2}$/.test(language)) {
      subtitleLanguageField.text = language
      root.subtitleSearchLanguageRequested(language)
    } else {
      subtitleLanguageField.text = root.subtitleSearchLanguage
    }
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
        meta: JellyCore.JellyfinState.configured ? "Connection settings" : "Connect to Jellyfin"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      PanelSeparator { foreground: root.foreground }

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
          ? "On a phone, TV, or browser already signed in to this server, open the profile menu → Quick Connect and enter the code. This panel signs in when that app approves it."
          : "This panel creates a short code. Enter that code in a Jellyfin app that is already signed in."
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

      PanelSectionHeader {
        visible: JellyCore.JellyfinState.configured && !root.pairing
        width: parent.width
        text: "OR SIGN IN WITH A PASSWORD"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Column {
        visible: JellyCore.JellyfinState.configured && !root.pairing
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "USERNAME"
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

        PanelSectionHeader {
          width: parent.width
          text: "PASSWORD"
          foreground: root.foreground
          fontFamily: root.fontFamily
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

          PanelSectionHeader {
            width: parent.width
            text: "API KEY"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

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
            text: "An API key is used instead of username and password. Create a dedicated key so this machine can be revoked independently."
            textFormat: Text.PlainText
            color: root.dimForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Column {
        visible: JellyCore.JellyfinState.configured
        width: parent.width
        spacing: Style.space(10)

        PanelSectionHeader {
          width: parent.width
          text: "PLAYBACK"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Toggle {
          id: autoPlayNextToggle
          width: parent.width
          label: "Auto-play next episode"
          description: "Continue with the next episode after the current episode ends."
          checked: root.autoPlayNextEpisode
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.autoPlayNextEpisodeRequested(!root.autoPlayNextEpisode)
          Keys.onEscapePressed: root.close()
        }

        Text {
          width: parent.width
          text: "Subtitle search language"
          textFormat: Text.PlainText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }

        TextField {
          id: subtitleLanguageField
          width: parent.width
          placeholderText: "en"
          maximumLength: 2
          foreground: root.foreground
          font.family: root.fontFamily
          inputMethodHints: Qt.ImhLatinOnly | Qt.ImhNoPredictiveText
          onAccepted: {
            root.commitSubtitleLanguage()
            autoPlayNextToggle.forceActiveFocus()
          }
          onActiveFocusChanged: {
            if (!activeFocus && root.opened) root.commitSubtitleLanguage()
          }
          Keys.onEscapePressed: root.close()
        }

        Text {
          width: parent.width
          text: "Two-letter language used by Ctrl+J in the player, such as en, nl, fr, or de."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        PanelSectionHeader {
          width: parent.width
          text: "APPEARANCE"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Toggle {
          id: newItemCountToggle
          width: parent.width
          label: "Show new-item count"
          description: "Display the number beside the Jellyfin icon in the bar."
          checked: root.showNewItemCount
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.showNewItemCountRequested(!root.showNewItemCount)
          Keys.onEscapePressed: root.close()
        }

        Toggle {
          id: jellyfinBlueToggle
          width: parent.width
          label: "Override theme colors"
          description: "Tint the bar icon Jellyfin blue when new items are available. Off keeps the current theme color."
          checked: root.useJellyfinBlueForNewItems
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.useJellyfinBlueForNewItemsRequested(!root.useJellyfinBlueForNewItems)
          Keys.onEscapePressed: root.close()
        }

        Row {
          width: parent.width
          spacing: Style.space(5)

          Button {
            id: closeSettingsButton
            width: (parent.width - parent.spacing) / 2
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

        Text {
          width: parent.width
          text: "Quick Connect never puts the session secret in this panel. Passwords and API keys are sent to the helper over stdin and stored in the desktop secret service. They are never written to plugin settings, command lines, logs, or cache. A failed test keeps the previous connection."
          textFormat: Text.PlainText
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
