package com.stbvs22.tts;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.Collections;
import java.util.List;

public class TTSService extends Service {

    private static final String TAG = "TTSService";
    private static final String CHANNEL_ID = "tts_server_channel";
    private static final int NOTIFICATION_ID = 1001;

    private Thread serverThread;
    private volatile boolean isRunning = false;
    private String serverIp = "";

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        serverIp = getDeviceIp();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "STOP".equals(intent.getAction())) {
            stopServer();
            return START_NOT_STICKY;
        }

        // Start foreground notification
        Notification notification = buildNotification("Starting TTS server...");
        startForeground(NOTIFICATION_ID, notification);

        // Launch server in background thread
        serverThread = new Thread(this::startPythonServer);
        serverThread.setDaemon(true);
        serverThread.start();

        return START_STICKY;
    }

    private void startPythonServer() {
        try {
            // Initialize Chaquopy Python runtime
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }

            Python py = Python.getInstance();
            Log.i(TAG, "Python started, calling server_main.start_server()");

            // Bind to all interfaces so other devices on LAN can connect
            String host = "0.0.0.0";
            int port = 5000;

            // Call server_main.py's start_server function
            py.getModule("server_main")
              .callAttr("start_server", host, port);

            isRunning = true;

            // Update notification with running status
            updateNotification(
                buildNotification(
                    "TTS Server running on http://" + serverIp + ":" + port
                )
            );

            Log.i(TAG, "TTS Server started on " + host + ":" + port);

        } catch (Exception e) {
            Log.e(TAG, "Failed to start TTS server", e);
            updateNotification(
                buildNotification("Server error: " + e.getMessage())
            );
        }
    }

    private void stopServer() {
        isRunning = false;
        try {
            if (Python.isStarted()) {
                Python py = Python.getInstance();
                py.getModule("server_main").callAttr("stop_server");
            }
        } catch (Exception e) {
            Log.e(TAG, "Error stopping server", e);
        }

        if (serverThread != null && serverThread.isAlive()) {
            serverThread.interrupt();
        }

        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        stopServer();
        super.onDestroy();
    }

    // ---- Notification helpers ----

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "TTS Server",
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Style-Bert-VITS2 TTS Server notification");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    private Notification buildNotification(String text) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("TTS Server")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build();
    }

    private void updateNotification(Notification notification) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, notification);
        }
    }

    // ---- Network helpers ----

    private String getDeviceIp() {
        try {
            List<NetworkInterface> interfaces =
                Collections.list(NetworkInterface.getNetworkInterfaces());
            for (NetworkInterface intf : interfaces) {
                List<java.net.InetAddress> addrs =
                    Collections.list(intf.getInetAddresses());
                for (java.net.InetAddress addr : addrs) {
                    if (!addr.isLoopbackAddress() && addr instanceof Inet4Address) {
                        return addr.getHostAddress();
                    }
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Error getting device IP", e);
        }
        return "127.0.0.1";
    }

    // ---- Status query (called from Activity) ----

    public boolean isRunning() {
        return isRunning;
    }

    public String getServerAddress() {
        return "http://" + serverIp + ":5000";
    }
}
