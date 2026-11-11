# OkHttp ships its own consumer rules; keep WorkManager workers instantiated by reflection.
-keep class com.hindidub.app.work.** { *; }
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
