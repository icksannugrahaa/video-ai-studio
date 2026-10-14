// PM2: one uvicorn process (API + UI + background render worker).
// Usage on the server:  pm2 start deploy/ecosystem.config.cjs && pm2 save
const path = require("path");
const root = path.resolve(__dirname, "..");

module.exports = {
  apps: [
    {
      name: "sandroid-ai-video",
      cwd: path.join(root, "backend"),
      script: path.join(root, ".venv", "bin", "python"),
      args: "-m app.main",
      interpreter: "none",
      instances: 1, // the render worker and job state assume a single process
      autorestart: true,
      max_restarts: 20,
      restart_delay: 3000,
      kill_timeout: 15000,
      env: { PYTHONUNBUFFERED: "1" },
      out_file: path.join(root, "data", "logs", "app.out.log"),
      error_file: path.join(root, "data", "logs", "app.err.log"),
      merge_logs: true,
      time: true,
    },
  ],
};
