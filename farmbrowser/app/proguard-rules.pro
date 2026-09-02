# FarmBrowser ProGuard rules
-keep class com.farmbrowser.stealth.proxy.** { *; }
-keep class com.farmbrowser.stealth.stealth.** { *; }
-keep class com.farmbrowser.stealth.browser.** { *; }
-keepclassmembers class * extends android.webkit.WebViewClient {
    public *;
}
-keepclassmembers class * extends android.webkit.WebChromeClient {
    public *;
}
-dontwarn okhttp3.**
-dontwarn okio.**
