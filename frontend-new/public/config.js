// Runtime configuration. The self-hosted dashboard image replaces this file at container start
// with values from CORTEXOPS_API_URL; an empty apiUrl falls back to VITE_API_URL or the hosted API.
window.__CORTEXOPS_CONFIG__ = window.__CORTEXOPS_CONFIG__ || { apiUrl: "" };
