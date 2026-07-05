package com.stbvs22.tts;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends AppCompatActivity {

    private Button btnStart, btnStop, btnHealthCheck;
    private TextView tvStatus, tvAddress, tvHealth;
    private Handler handler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        btnStart = findViewById(R.id.btn_start);
        btnStop = findViewById(R.id.btn_stop);
        btnHealthCheck = findViewById(R.id.btn_health);
        tvStatus = findViewById(R.id.tv_status);
        tvAddress = findViewById(R.id.tv_address);
        tvHealth = findViewById(R.id.tv_health);

        btnStart.setOnClickListener(v -> startServer());
        btnStop.setOnClickListener(v -> stopServer());
        btnHealthCheck.setOnClickListener(v -> checkHealth());

        updateUiState(false);
    }

    private void startServer() {
        Intent intent = new Intent(this, TTSService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        updateUiState(true);
        tvStatus.setText("Starting...");
        Toast.makeText(this, "Starting TTS server...", Toast.LENGTH_SHORT).show();

        // Poll for server readiness
        handler.postDelayed(() -> {
            checkHealth();
        }, 3000);
    }

    private void stopServer() {
        Intent intent = new Intent(this, TTSService.class);
        intent.setAction("STOP");
        startService(intent);
        updateUiState(false);
        tvStatus.setText("Stopped");
        tvHealth.setText("");
        Toast.makeText(this, "TTS server stopped", Toast.LENGTH_SHORT).show();
    }

    private void checkHealth() {
        new Thread(() -> {
            try {
                URL url = new URL("http://127.0.0.1:5000/health");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(2000);
                conn.setReadTimeout(2000);

                int code = conn.getResponseCode();
                BufferedReader reader = new BufferedReader(
                    new InputStreamReader(conn.getInputStream())
                );
                String response = reader.readLine();

                runOnUiThread(() -> {
                    tvHealth.setText("Health: " + (code == 200 ? "OK" : "FAIL") +
                                     " (" + code + ")");
                    tvStatus.setText("Running");
                });

                conn.disconnect();
            } catch (Exception e) {
                runOnUiThread(() -> {
                    tvHealth.setText("Health: unreachable");
                    tvStatus.setText("Starting...");
                });
            }
        }).start();
    }

    private void updateUiState(boolean running) {
        btnStart.setEnabled(!running);
        btnStop.setEnabled(running);
        btnHealthCheck.setEnabled(running);
        tvAddress.setText(
            running ? "Server: http://<device_ip>:5000" : "Server not running"
        );
    }
}
