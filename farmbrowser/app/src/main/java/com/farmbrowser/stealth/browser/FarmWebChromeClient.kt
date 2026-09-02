package com.farmbrowser.stealth.browser

import android.app.Activity
import android.net.Uri
import android.webkit.*
import android.widget.EditText
import android.widget.ProgressBar

/**
 * Custom WebChromeClient for progress, title, and permission handling.
 */
class FarmWebChromeClient(
    private val activity: Activity,
    private val progressBar: ProgressBar,
    private val urlBar: EditText
) : WebChromeClient() {

    override fun onProgressChanged(view: WebView?, newProgress: Int) {
        activity.runOnUiThread {
            progressBar.progress = newProgress
            progressBar.visibility = if (newProgress < 100) {
                android.view.View.VISIBLE
            } else {
                android.view.View.GONE
            }
        }
    }

    override fun onReceivedTitle(view: WebView?, title: String?) {
        // Could update window title if we had a title bar
    }

    override fun onReceivedIcon(view: WebView?, icon: android.graphics.Bitmap?) {
        // Could update favicon in URL bar
    }

    override fun onShowFileChooser(
        webView: WebView?,
        filePathCallback: ValueCallback<Array<Uri>>?,
        fileChooserParams: FileChooserParams?
    ): Boolean {
        // Simplified file chooser — returns false to skip
        filePathCallback?.onReceiveValue(null)
        return true
    }

    override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
        // Suppress console noise in production
        return true
    }

    override fun onCreateWindow(
        view: WebView?, isDialog: Boolean, isUserGesture: Boolean, resultMsg: android.os.Message?
    ): Boolean {
        // Allow popup windows (some sites need them)
        val newWebView = WebView(activity)
        newWebView.webViewClient = view?.webViewClient ?: FarmWebViewClient(
            activity, urlBar, {}
        )
        val transport = resultMsg?.obj as? WebView.WebViewTransport
        transport?.webView = newWebView
        resultMsg?.sendToTarget()
        return true
    }

    override fun onCloseWindow(window: WebView?) {
        window?.destroy()
    }
}
