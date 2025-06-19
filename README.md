# Geodini

A natural language geocoding API.

## Helm Chart Installation

This application can be deployed using the provided Helm chart located in the `geodini-chart` directory.

### Prerequisites

*   Kubernetes cluster (e.g., Minikube, Kind, or a cloud provider's K8s service)
*   Helm v3 installed
*   `kubectl` configured to connect to your cluster

### Installation Steps

1.  **Navigate to the chart directory:**
    ```bash
    cd geodini-chart
    ```

2.  **Review and customize values (Optional):**
    Before installing, you might want to customize the deployment by overriding default values. Create a `my-values.yaml` file or inspect `values.yaml` for available options.
    Key values you might want to override:
    *   `postgres.password`: **It is highly recommended to change the default PostgreSQL password.**
    *   `ingress.enabled`: Set to `true` if you have an Ingress controller and want to expose the application via Ingress.
    *   `ingress.hosts`: Configure your desired hostname(s).
    *   `ingress.tls`: Configure TLS secrets if using HTTPS.
    *   `appDataPersistence.size` and `postgres.persistence.size`: Adjust storage sizes as needed.
    *   Image tags for `api`, `frontend`, and `api.initContainer` if you want to use specific versions.

3.  **Install the chart:**
    To install the chart with the release name `geodini`:
    ```bash
    helm install geodini .
    ```
    If you have a custom values file:
    ```bash
    helm install geodini . -f my-values.yaml
    ```
    To install into a specific namespace:
    ```bash
    helm install geodini . --namespace geodini-ns --create-namespace
    ```

4.  **Check deployment status:**
    ```bash
    kubectl get pods -n <your-namespace-if-any>
    kubectl get svc -n <your-namespace-if-any>
    ```
    Wait for all pods to be in the `Running` state. The `NOTES.txt` output from the Helm install command will also provide useful information on how to access the application.

### Accessing the Application

*   **Via Port-Forward (if Ingress is not enabled):**
    The `NOTES.txt` from the Helm installation will provide `kubectl port-forward` commands. Typically:
    ```bash
    # Forward Frontend
    kubectl port-forward svc/geodini-frontend 8080:80 # Access at http://localhost:8080
    # Forward API (if direct access needed)
    kubectl port-forward svc/geodini-api 9000:9000
    ```
*   **Via Ingress (if enabled):**
    Access the application via the host and paths configured in your `values.yaml` (e.g., `http://chart-example.local/` or `https://your.domain.com/`).

### Upgrading the Chart

To upgrade an existing release:
```bash
helm upgrade geodini . -f my-values.yaml # Or without -f if no custom values
```

### Uninstalling the Chart

To uninstall/delete the `geodini` release:
```bash
helm uninstall geodini
```
This will remove all Kubernetes components associated with the chart. PersistentVolumeClaims (PVCs) might need to be deleted manually if you want to remove the persisted data:
```bash
kubectl delete pvc geodini-app-data geodini-postgres-data
```
(Adjust PVC names based on your release name).
