export function escapeVegaField(field) {
  return field.replace(/[.\\[\]'"]/g, "\\$&");
}
