import QtQuick 2.15
import "."

// 后端锁态是唯一解锁依据；求助与通话入口保持可达。
Item {
  id: lk
  property bool locked: !backend.fixture
  property bool configured: backend.fixture
  property bool faceEnrolled: backend.fixture
  property bool faceAvailable: backend.fixture
  property bool statusKnown: backend.fixture
  property bool online: backend.fixture
  property bool serverLocked: !backend.fixture
  property bool applyingState: false
  property bool managing: false
  property bool polling: false
  property bool pinBusy: false
  property bool faceBusy: false
  property bool lockBusy: false
  property bool previewPolling: false
  property string previewImage: ""
  property double previewAt: 0
  readonly property bool previewing: managing && faceBusy && !locked && online
  property int revision: 0
  property int retryAfter: 0
  property string pin: ""
  property string firstPin: ""
  property bool confirming: false
  property string message: ""
  property string serviceError: ""
  readonly property bool settingUp: statusKnown && !configured
  readonly property bool showing: locked || managing || settingUp
  visible: showing
  focus: showing
  z: 45

  function clearPin() { pin = ""; firstPin = ""; confirming = false }
  function setLocked(value) {
    applyingState = true
    locked = value
    applyingState = false
  }
  function validStatus(data) {
    return data && typeof data.configured === "boolean" && typeof data.locked === "boolean"
  }
  function applyStatus(data) {
    if (!validStatus(data)) { disconnected("锁屏状态暂不可用，请稍后重试"); return }
    statusKnown = true
    online = true
    configured = data.configured
    serverLocked = data.locked
    faceEnrolled = !!data.face_enrolled
    faceAvailable = !!data.face_available
    retryAfter = Math.max(0, Math.ceil(Number(data.retry_after) || 0))
    serviceError = data.error || ""
    if (serverLocked && !locked) { clearPin(); managing = false; app.closeOverlays() }
    setLocked(serverLocked)
  }
  function disconnected(error) {
    online = false
    serverLocked = true
    setLocked(true)
    managing = false
    clearPin()
    message = ""
    serviceError = error || "无法连接本机服务，屏幕保持锁定"
  }
  function refreshStatus() {
    if (backend.fixture || polling || lockBusy) return
    polling = true
    var token = revision
    backend.request("GET", "/api/screen-auth/status", undefined, function (ok, data, error) {
      polling = false
      if (token !== revision) return
      if (ok) applyStatus(data)
      else disconnected(error)
    })
  }
  function refreshPreview() {
    if (!previewing || previewPolling || backend.fixture) return
    previewPolling = true
    var token = revision
    backend.request("GET", "/api/screen-auth/preview", undefined, function (ok, data, error) {
      previewPolling = false
      if (token !== revision || !previewing) return
      previewImage = ok && data && data.active ? data.image || "" : ""
      previewAt = Date.now()
    })
  }
  function action(kind, body) {
    if (backend.fixture) { clearPin(); message = "截图预览，不执行身份验证"; return }
    var token = ++revision
    if (kind === "face" || kind === "enroll") faceBusy = true
    else if (kind === "lock") lockBusy = true
    else pinBusy = true
    message = ""
    backend.request("POST", "/api/screen-auth/" + kind, body, function (ok, data, error) {
      if (kind === "face" || kind === "enroll") faceBusy = false
      else if (kind === "lock") lockBusy = false
      else pinBusy = false
      if (token !== revision) return
      ++revision // 丢弃验证期间发出的旧状态响应。
      if (ok) {
        if (validStatus(data)) applyStatus(data)
        else refreshStatus()
        if (kind === "setup") managing = false
        if (kind === "enroll") { managing = false; message = "本机人脸已录入" }
      } else {
        message = (data && data.error) || error || "操作未完成，请重试或使用 PIN"
        if (data && data.retry_after !== undefined)
          retryAfter = Math.max(0, Math.ceil(Number(data.retry_after) || 0))
        refreshStatus()
      }
    })
    // 请求已序列化；不把 PIN 留在界面状态、设置或日志中。
    clearPin()
    if (body) { body.pin = ""; body.confirm = "" }
  }
  function requestLock() {
    clearPin()
    managing = false
    app.closeOverlays()
    if (backend.fixture) return
    if (!statusKnown || !online) { setLocked(true); refreshStatus(); return }
    if (!configured) { setLocked(false); return }
    if (!lockBusy) action("lock", {})
  }
  function openSettings() {
    clearPin()
    message = ""
    if (!statusKnown || !online || (configured && serverLocked)) {
      setLocked(true)
      refreshStatus()
      return
    }
    managing = true
    refreshStatus()
  }
  function addDigit(digit) {
    if (!online || pinBusy || lockBusy || backend.fixture || pin.length >= 6) return
    if (/^[0-9]$/.test(digit)) pin += digit
  }
  function submitPin() {
    if (!online || pinBusy || lockBusy || retryAfter > 0 || !/^[0-9]{6}$/.test(pin)) return
    if (managing && faceBusy) return
    if (settingUp && !confirming) {
      firstPin = pin; pin = ""; confirming = true; message = ""; return
    }
    if (settingUp) {
      if (firstPin !== pin) { clearPin(); message = "两次 PIN 不一致，请重新输入"; return }
      action("setup", { pin: firstPin, confirm: pin })
    } else action(managing ? "enroll" : "pin", { pin: pin })
  }
  onLockedChanged: {
    if (applyingState || backend.fixture) return
    if (locked) requestLock()
    else if (serverLocked || !statusKnown || !online) setLocked(true)
  }
  onShowingChanged: if (!showing) { clearPin(); previewImage = "" }
  onPreviewingChanged: { previewImage = ""; if (previewing) refreshPreview() }
  Component.onCompleted: refreshStatus()
  Timer { interval: 250; repeat: true; running: lk.previewing
    onTriggered: { if (lk.previewImage && Date.now() - lk.previewAt > 1000) lk.previewImage = ""; lk.refreshPreview() } }
  Timer { interval: 1500; repeat: true; running: !backend.fixture; onTriggered: lk.refreshStatus() }
  Timer { interval: 1000; repeat: true; running: lk.retryAfter > 0; onTriggered: lk.retryAfter = Math.max(0, lk.retryAfter - 1) }
  Keys.onPressed: {
    if (/^[0-9]$/.test(event.text)) { addDigit(event.text); event.accepted = true }
    else if (event.key === Qt.Key_Backspace) { pin = pin.slice(0, -1); event.accepted = true }
    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { submitPin(); event.accepted = true }
    else if (event.key === Qt.Key_Escape) { if (managing && !pinBusy && !faceBusy) { managing = false; clearPin() }; event.accepted = true }
  }

  Rectangle { anchors.fill: parent; color: "#141A22" }
  MouseArea { anchors.fill: parent }

  Flickable {
    id: viewport
    anchors { left: parent.left; right: parent.right; top: parent.top; bottom: help.top; bottomMargin: 12 }
    clip: true; contentWidth: width; contentHeight: panel.height + 40
    boundsBehavior: Flickable.StopAtBounds
    Column {
      id: panel
      x: (viewport.width - width) / 2; y: 20
      width: Math.min(480, viewport.width - 40); spacing: 14
      Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "lock"; color: "#FFFFFF"; size: 42 }
      Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; px: 30; strong: true; color: "#FFFFFF"
        text: !lk.statusKnown ? "正在确认锁屏状态" : lk.settingUp ? "设置本机 PIN" : lk.managing ? "录入彩色人脸" : "屏幕已锁定" }
      Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; px: 20; color: "#CDD5DF"
        text: lk.settingUp ? (lk.confirming ? "请再次输入刚才的六位 PIN" : "请设置六位数字 PIN，用于解锁与人脸管理")
              : lk.managing ? (lk.previewing ? "正在显示彩色取景，请保持正对镜头" : "再次输入 PIN 后录入彩色人脸，请正对相机") : "输入六位 PIN，或点人脸解锁；求助仍可用" }
      Rectangle {
        visible: lk.previewing
        width: parent.width; height: 320; radius: 14; color: "#090D13"; clip: true
        Image { anchors.fill: parent; source: lk.previewImage; fillMode: Image.PreserveAspectFit; cache: false; asynchronous: true }
        Rectangle { anchors.centerIn: parent; width: 150; height: 210; radius: 70; color: "transparent"; border.color: "#BBD7F0"; border.width: 2 }
        Txt { anchors.centerIn: parent; width: parent.width - 24; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: "#FFFFFF"; px: 20
          visible: !lk.previewImage; text: "正在开启录入画面…" }
      }
      Txt { visible: lk.previewing; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: "#CDD5DF"; px: 20
        text: "脸距镜头约 50～70 cm，正对取景框并保持不动" }
      Rectangle {
        visible: !lk.previewing
        width: parent.width; height: 58; radius: 14; color: "#263343"
        Txt { anchors.centerIn: parent; text: Array(lk.pin.length + 1).join("●") + Array(7 - lk.pin.length).join("○")
          px: 28; color: "#FFFFFF"; font.letterSpacing: 12 }
      }
      Grid {
        visible: !lk.previewing
        width: parent.width; columns: 3; spacing: 10
        Repeater {
          model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "清空", "0", "删除"]
          Btn {
            width: (panel.width - 20) / 3; height: 58; text: modelData; px: 25
            bg: "#263343"; fg: "#FFFFFF"
            enabled: lk.online && !lk.pinBusy && !lk.lockBusy && !backend.fixture
            onClicked: {
              lk.forceActiveFocus()
              if (modelData === "清空") lk.clearPin()
              else if (modelData === "删除") lk.pin = lk.pin.slice(0, -1)
              else lk.addDigit(modelData)
            }
          }
        }
      }
      Btn {
        visible: !lk.previewing
        width: parent.width; height: 60; bg: Theme.blue; fg: "#FFFFFF"; busy: lk.pinBusy || (lk.managing && lk.faceBusy)
        text: lk.retryAfter > 0 ? lk.retryAfter + " 秒后可重试" : lk.pinBusy ? "正在验证…" : lk.managing && lk.faceBusy ? "正在录入，请正对相机…"
              : lk.settingUp ? (lk.confirming ? "确认并启用 PIN" : "下一步") : lk.managing ? "验证 PIN 并录入彩色人脸" : "PIN 解锁"
        enabled: lk.online && !lk.pinBusy && !(lk.managing && lk.faceBusy) && !lk.lockBusy && lk.pin.length === 6 && lk.retryAfter === 0 && !backend.fixture
        onClicked: lk.submitPin()
      }
      Btn {
        width: parent.width; height: 58; bg: "#263343"; fg: "#FFFFFF"; busy: lk.faceBusy
        visible: lk.configured && !lk.managing
        text: lk.faceBusy ? "正在识别，可改用 PIN" : "人脸解锁"
        enabled: lk.online && lk.faceEnrolled && lk.faceAvailable && !lk.faceBusy && !lk.pinBusy && !lk.lockBusy && !backend.fixture
        onClicked: lk.action("face", {})
      }
      Txt {
        width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; px: 18; color: "#CDD5DF"
        text: lk.managing ? "仅彩色人脸识别，照片或视频可能冒用；PIN 可备用。"
              : lk.configured && !lk.faceEnrolled ? "请用 PIN 解锁，在设置中录入彩色人脸"
              : lk.configured && !lk.faceAvailable ? "彩色相机暂不可用，请使用 PIN" : "彩色人脸解锁"
      }
      Txt { width: parent.width; visible: !!text; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; px: 20; color: "#FFCD99"
        text: backend.fixture ? "截图预览，不执行身份验证" : lk.message || lk.serviceError }
      Btn {
        width: parent.width; height: 54; visible: lk.managing && lk.configured; text: "退出人脸管理"; bg: "#263343"; fg: "#FFFFFF"
        enabled: !lk.pinBusy && !lk.faceBusy
        onClicked: { lk.managing = false; lk.clearPin() }
      }
    }
  }
  HelpButton {
    id: help
    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
    anchors.margins: 16
  }
}
