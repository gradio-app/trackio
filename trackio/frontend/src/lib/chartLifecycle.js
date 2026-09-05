function finalizeView(view) {
  if (!view) return;
  try {
    view.finalize();
  } catch (error) {
    console.warn("Failed to finalize Vega view:", error);
  }
}

function clearElement(element) {
  if (!element) return;
  element.replaceChildren();
}

export function createVegaViewManager() {
  let current = null;
  let currentElement = null;
  let generation = 0;
  let destroyed = false;

  return {
    get current() {
      return current;
    },

    async replace(create, element = null) {
      if (destroyed) return null;

      const renderGeneration = ++generation;
      finalizeView(current);
      if (currentElement && currentElement !== element) {
        clearElement(currentElement);
      }
      current = null;
      currentElement = null;

      const result = await create();
      const next = result?.view;
      if (!next) {
        throw new Error("Vega embed did not return a view");
      }

      if (destroyed || renderGeneration !== generation) {
        finalizeView(next);
        if (element && element !== currentElement) clearElement(element);
        return null;
      }

      current = next;
      currentElement = element;
      return result;
    },

    clear() {
      generation += 1;
      finalizeView(current);
      clearElement(currentElement);
      current = null;
      currentElement = null;
    },

    destroy() {
      destroyed = true;
      generation += 1;
      finalizeView(current);
      clearElement(currentElement);
      current = null;
      currentElement = null;
    },
  };
}

export function observeNearViewport(element, onChange) {
  if (typeof IntersectionObserver === "undefined") {
    onChange(true);
    return () => {};
  }

  const observer = new IntersectionObserver(
    ([entry]) => onChange(entry?.isIntersecting ?? false),
    { rootMargin: "600px 0px" },
  );
  observer.observe(element);
  return () => observer.disconnect();
}
