import axios from 'axios';

let baseURL;

if (process.env.NODE_ENV === 'production') {
  // In production, assume the API is served from the same origin,
  // under the /api path. Your reverse proxy (Nginx) will handle routing this.
  // If your API is at the root of the domain, you can use '/' or just an empty string.
  baseURL = '/'; // Axios will prepend this to relative URLs if they don't start with http
                 // So an axios.get('/api/containers') would go to https://yourdomain.com/api/containers
} else {
  // For development, use the explicit URL from .env or fallback to localhost:5000
  baseURL = process.env.REACT_APP_API_URL || 'http://localhost:5000';
}

const api = axios.create({
  baseURL: baseURL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Optional: Add interceptors for handling responses or requests globally
// e.g., automatically redirecting to login on 401 Unauthorized
api.interceptors.response.use(
  (response) => response, // Simply return successful responses
  (error) => {
    if (error.response && error.response.status === 401) {
      // Handle unauthorized access - e.g., redirect to login
      // Avoid infinite loops if login page itself causes 401
      if (window.location.pathname !== '/login') {
        console.warn('Unauthorized access detected, redirecting to login.');
        // Maybe clear some local storage state before redirecting
        // window.location.href = '/login'; // Hard redirect might be better sometimes
      }
    }
    // Important: Reject the promise so downstream .catch() handlers work
    return Promise.reject(error);
  }
);


export default api;