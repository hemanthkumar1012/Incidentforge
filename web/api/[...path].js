import { proxy } from "./_proxy.js";

export const config = { maxDuration: 30 };

export default {
  fetch(request) {
    return proxy(request, { origin: process.env.API_ORIGIN, env: process.env.VERCEL_ENV ?? "production" });
  },
};
