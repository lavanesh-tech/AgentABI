output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.agentabi.name
}

output "network_name" {
  value = google_compute_network.agentabi.name
}

output "gke_subnet_name" {
  value = google_compute_subnetwork.gke.name
}

output "gke_cluster_name" {
  value = google_container_cluster.agentabi.name
}

output "gke_cluster_location" {
  value = google_container_cluster.agentabi.location
}

output "cloud_sql_instance_name" {
  value = google_sql_database_instance.postgres.name
}

output "cloud_sql_private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}

output "secret_names" {
  value = [
    google_secret_manager_secret.openai_api_key.secret_id,
    google_secret_manager_secret.jwt_signing_key.secret_id,
    google_secret_manager_secret.github_oauth_client_id.secret_id,
    google_secret_manager_secret.github_oauth_client_secret.secret_id,
  ]
}
