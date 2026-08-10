import json
import os
import unittest
from unittest.mock import MagicMock, patch

from keepalive import (
    mask_uri,
    parse_mongodb_uris,
    ping_and_modify_cluster,
    send_discord_notification,
)


class TestMongoDBKeepAlive(unittest.TestCase):

    def test_mask_uri_standard(self):
        uri = "mongodb+srv://dbuser:MySecretPassword123@cluster0.abcde.mongodb.net/test?retryWrites=true"
        masked = mask_uri(uri)
        self.assertNotIn("MySecretPassword123", masked)
        self.assertTrue(masked.startswith("mongodb+srv://db***:****@cluster0.abcde.mongodb.net"))

    def test_mask_uri_invalid(self):
        self.assertEqual(mask_uri(""), "<invalid-uri>")
        self.assertEqual(mask_uri(None), "<invalid-uri>")

    @patch.dict(os.environ, {"MONGODB_URIS": "mongodb+srv://u1:p1@cluster1.net, mongodb+srv://u2:p2@cluster2.net"}, clear=True)
    def test_parse_uris_comma_separated(self):
        clusters = parse_mongodb_uris()
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["uri"], "mongodb+srv://u1:p1@cluster1.net")
        self.assertEqual(clusters[1]["uri"], "mongodb+srv://u2:p2@cluster2.net")

    @patch.dict(os.environ, {
        "MONGODB_URIS": json.dumps([
            {"name": "Production", "uri": "mongodb+srv://u1:p1@cluster1.net"},
            {"name": "Staging", "uri": "mongodb+srv://u2:p2@cluster2.net"}
        ])
    }, clear=True)
    def test_parse_uris_json_array(self):
        clusters = parse_mongodb_uris()
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["name"], "Production")
        self.assertEqual(clusters[1]["name"], "Staging")

    @patch.dict(os.environ, {
        "MONGODB_URI_PRIMARY": "mongodb+srv://u1:p1@cluster1.net",
        "MONGODB_URI_SECONDARY": "mongodb+srv://u2:p2@cluster2.net"
    }, clear=True)
    def test_parse_uris_individual_env_vars(self):
        clusters = parse_mongodb_uris()
        self.assertEqual(len(clusters), 2)
        names = [c["name"] for c in clusters]
        self.assertIn("PRIMARY", names)
        self.assertIn("SECONDARY", names)

    @patch("keepalive.MongoClient")
    def test_ping_and_modify_cluster_success(self, mock_mongo_client):
        # Mocking MongoDB Client and DB collection methods
        mock_client_inst = MagicMock()
        mock_mongo_client.return_value = mock_client_inst
        mock_client_inst.admin.command.return_value = {"ok": 1}

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_client_inst.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_collection

        mock_collection.find_one.return_value = {"_id": "keepalive_ping_record", "total_pings": 5}

        cluster_info = {"name": "TestCluster", "uri": "mongodb+srv://user:pass@cluster.net"}
        result = ping_and_modify_cluster(cluster_info)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["total_pings"], 5)
        mock_collection.update_one.assert_called_once()

    @patch("keepalive.requests.post")
    def test_send_discord_notification(self, mock_post):
        mock_post.return_value.status_code = 204
        results = [
            {"name": "Cluster1", "masked_uri": "mongodb+srv://u***:****@c1", "status": "SUCCESS", "duration_ms": 120, "total_pings": 3, "message": "OK"}
        ]
        success = send_discord_notification("https://discord.com/api/webhooks/test", results)
        self.assertTrue(success)
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
