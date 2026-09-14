function finalizeView(view) {
  if (!view) return;
  try {
    view.finalize();
  } catch (error) {
    console.warn("Failed to finalize Vega view:", error);
  }
}

function holdElementHeight(element) {
  if (!element?.style || typeof element.getBoundingClientRect !== "function") {
    return;
  }
  const height = element.getBoundingClientRect().height;
  if (height > 0) element.style.height = `${height}px`;
}

function releaseElementHeight(element) {
  element?.style?.removeProperty("height");
}

function clearElement(element, holdHeight = false) {
  if (!element) return;
  if (holdHeight) holdElementHeight(element);
  element.replaceChildren();
}

export function createVegaViewManager() {
  let current = null;
  let currentElement = null;
  let generation = 0;
  let destroyed = false;
  let rendering = false;
  let queued = null;

  function cancelQueued() {
    if (!queued) return;
    queued.resolve(null);
    queued = null;
  }

  async function execute(request) {
    if (destroyed || request.generation !== generation) return null;

    finalizeView(current);
    if (currentElement && currentElement !== request.element) {
      clearElement(currentElement);
    }
    current = null;
    currentElement = null;

    let result;
    try {
      result = await request.create();
      if (!result?.view) throw new Error("Vega embed did not return a view");
    } catch (error) {
      clearElement(request.element);
      releaseElementHeight(request.element);
      throw error;
    }
    const next = result.view;

    if (destroyed || request.generation !== generation) {
      finalizeView(next);
      clearElement(request.element, true);
      return null;
    }

    current = next;
    currentElement = request.element;
    releaseElementHeight(request.element);
    return result;
  }

  function start(request) {
    rendering = true;
    void (async () => {
      try {
        request.resolve(await execute(request));
      } catch (error) {
        request.reject(error);
      } finally {
        rendering = false;
        const next = queued;
        queued = null;
        if (next) start(next);
      }
    })();
  }

  return {
    get current() {
      return current;
    },

    replace(create, element = null) {
      if (destroyed) return Promise.resolve(null);

      const requestGeneration = ++generation;
      return new Promise((resolve, reject) => {
        const request = {
          create,
          element,
          generation: requestGeneration,
          resolve,
          reject,
        };
        if (rendering) {
          cancelQueued();
          queued = request;
        } else {
          start(request);
        }
      });
    },

    clear() {
      generation += 1;
      cancelQueued();
      finalizeView(current);
      clearElement(currentElement, true);
      current = null;
      currentElement = null;
    },

    destroy() {
      destroyed = true;
      generation += 1;
      cancelQueued();
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
    (entries) =>
      onChange(entries[entries.length - 1]?.isIntersecting ?? false),
    { rootMargin: "600px 0px" },
  );
  observer.observe(element);
  return () => observer.disconnect();
}
