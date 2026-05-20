// Create the application user on the enterprise database.
//
// The user gets `readWrite` on the enterprise DB so the LangGraph Mongo
// checkpointer can persist runs into `lg_checkpoints`. Application read-only
// behavior is enforced by mcp/db.py:validate_spec at the API layer, not by
// Mongo role.
//
// Init scripts run only when /data/db is empty, so this is effectively
// idempotent. Wrap in try/catch so a re-run on a partially-seeded volume
// doesn't crash the container.
(function () {
  try {
    db = db.getSiblingDB("admin");
    try {
      db.createUser({
        user: "app",
        pwd: "app",
        roles: [
          { role: "readWrite", db: "enterprise" },
        ],
      });
      print("created user app");
    } catch (e) {
      print("createUser skipped: " + e.message);
    }
  } catch (e) {
    print("00-users.js error: " + e.message);
  }
})();
