import { api } from "./types-and-api";
import { createSpacesApi, type Transport } from "./spaces-api";

const transport: Transport = (path, init) => api(path, init);
export const spacesApi = createSpacesApi(transport);
