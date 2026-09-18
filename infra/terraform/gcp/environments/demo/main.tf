resource "google_artifact_registry_repository" "agentabi" {
  location      = var.region
  repository_id = "agentabi"
  description   = "Container images for AgentABI recruiter demo"
  format        = "DOCKER"

  labels = local.labels
}

resource "google_compute_network" "agentabi" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "gke" {
  name          = "${local.name_prefix}-gke-subnet"
  region        = var.region
  network       = google_compute_network.agentabi.id
  ip_cidr_range = "10.42.0.0/20"

  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.48.0.0/14"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.52.0.0/20"
  }
}

resource "google_container_cluster" "agentabi" {
  name     = "${local.name_prefix}-gke"
  location = var.region

  enable_autopilot    = true
  deletion_protection = false

  network    = google_compute_network.agentabi.id
  subnetwork = google_compute_subnetwork.gke.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR"
  }

  resource_labels = local.labels
}

resource "google_compute_global_address" "private_services" {
  name          = "${local.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.agentabi.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.agentabi.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_sql_database_instance" "postgres" {
  name             = "${local.name_prefix}-postgres"
  region           = var.region
  database_version = "POSTGRES_16"

  deletion_protection = false

  depends_on = [
    google_service_networking_connection.private_services
  ]

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.agentabi.id
    }

    backup_configuration {
      enabled = false
    }

    user_labels = local.labels
  }
}

resource "google_sql_database" "agentabi" {
  name     = "agentabi"
  instance = google_sql_database_instance.postgres.name
}

resource "google_secret_manager_secret" "openai_api_key" {
  secret_id = "${local.name_prefix}-openai-api-key"

  replication {
    auto {}
  }

  labels = local.labels
}

resource "google_secret_manager_secret" "jwt_signing_key" {
  secret_id = "${local.name_prefix}-jwt-signing-key"

  replication {
    auto {}
  }

  labels = local.labels
}

resource "google_secret_manager_secret" "github_oauth_client_id" {
  secret_id = "${local.name_prefix}-github-oauth-client-id"

  replication {
    auto {}
  }

  labels = local.labels
}

resource "google_secret_manager_secret" "github_oauth_client_secret" {
  secret_id = "${local.name_prefix}-github-oauth-client-secret"

  replication {
    auto {}
  }

  labels = local.labels
}
