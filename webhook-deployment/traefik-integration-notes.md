# Traefik Integration for Webhook Deployment

## Integration with matrix-docker-ansible-deploy

Since you're using the [matrix-docker-ansible-deploy](https://github.com/spantaleev/matrix-docker-ansible-deploy) playbook, here are the recommended approaches to integrate the webhook service:

### Option 1: Subpath Configuration (Recommended)

Add this to your Ansible inventory file under `group_vars/matrix_servers/vars.yml`:

```yaml
# Custom Traefik configuration for Matrix PDF Bot webhook deployment
matrix_playbook_traefik_custom_proxy_configuration: |
  - name: matrix-pdf-bot-webhook
    router:
      rule: "Host(`{{ matrix_server_fqdn_matrix }}`) && PathPrefix(`/matrix-pdf-bot-webhook`)"
      service: matrix-pdf-bot-webhook-service
      middlewares:
        - matrix-pdf-bot-webhook-headers
      tls:
        certResolver: "{{ devture_traefik_certResolver_primary }}"
    service:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8080"
    middleware:
      headers:
        customRequestHeaders:
          X-Forwarded-Proto: "https"
        customResponseHeaders:
          X-Frame-Options: "DENY"
          X-Content-Type-Options: "nosniff"
```

### Option 2: Auxiliary Service (Alternative)

If you prefer to manage this as a separate auxiliary service:

```yaml
# In your vars.yml file
matrix_playbook_auxiliary_docker_services_enabled: true

matrix_playbook_auxiliary_docker_services_list:
  - name: matrix-pdf-bot-webhook
    docker_src_files_path: "{{ playbook_dir }}/webhook-deployment/"
    systemd_services_to_stop_for_maintenance_list:
      - matrix-pdf-bot-webhook
```

### Option 3: Manual File Addition

If the above options don't work with your current setup, manually add the configuration:

1. Add the webhook configuration to your Traefik dynamic config directory:

   ```bash
   # Usually located at /matrix/traefik/config/
   cp traefik-config.yml /matrix/traefik/config/matrix-pdf-bot-webhook.yml
   ```

2. Restart Traefik to pick up the new configuration:

   ```bash
   systemctl restart matrix-traefik
   ```

## URL Endpoints

After integration, your webhook will be available at:

- **Health check**: `https://matrix.yourdomain.com/matrix-pdf-bot-webhook/health`
- **GitHub webhook**: `https://matrix.yourdomain.com/matrix-pdf-bot-webhook/deploy`

## Security Considerations

1. The webhook service runs on `127.0.0.1:8080` (localhost only)
2. Traefik provides the public HTTPS endpoint
3. GitHub webhook secret provides authentication
4. Additional headers prevent common web attacks

## Testing the Configuration

1. Check if Traefik picked up the configuration:

   ```bash
   curl https://matrix.yourdomain.com/matrix-pdf-bot-webhook/health
   ```

2. Expected response:

   ```json
   {
     "status": "healthy",
     "service": "matrix-pdf-bot-webhook",
     "timestamp": "2024-01-01T12:00:00.000000"
   }
   ```

