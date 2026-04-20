<script>
  import { tick } from "svelte";

  let {
    label = "Dropdown",
    info = "",
    value = $bindable(null),
    choices = [],
    filterable = true,
    showLabel = true,
  } = $props();

  let filterInput;
  let showOptions = $state(false);
  let inputText = $state("");
  let activeIndex = $state(null);
  let filteredIndices = $state([]);
  let inputWidth = $state(0);
  let top = $state(null);
  let bottom = $state(null);
  let maxHeight = $state(300);

  let selectedIndex = $derived(
    value !== null ? choices.indexOf(value) : -1,
  );

  $effect(() => {
    if (showOptions) return;
    if (value !== null && choices.includes(value)) {
      inputText = value;
    } else {
      inputText = "";
    }
  });

  $effect(() => {
    filteredIndices = showOptions ? filterChoices(inputText) : choices.map((_, i) => i);
  });

  function filterChoices(text) {
    if (!text) return choices.map((_, i) => i);
    const lower = text.toLowerCase();
    return choices
      .map((c, i) => (c.toLowerCase().includes(lower) ? i : -1))
      .filter((i) => i >= 0);
  }

  function handleFocus() {
    inputText = "";
    filteredIndices = choices.map((_, i) => i);
    showOptions = true;
    if (filterInput) {
      const rect = filterInput.closest(".wrap")?.getBoundingClientRect();
      if (rect) {
        inputWidth = rect.width;
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;
        if (spaceBelow >= 200 || spaceBelow > spaceAbove) {
          top = `${rect.bottom}px`;
          bottom = null;
          maxHeight = spaceBelow - 16;
        } else {
          bottom = `${window.innerHeight - rect.top}px`;
          top = null;
          maxHeight = spaceAbove - 16;
        }
      }
    }
  }

  function handleBlur() {
    if (choices.includes(inputText)) {
      value = inputText;
    } else if (value !== null) {
      inputText = value;
    } else {
      inputText = "";
    }
    showOptions = false;
    activeIndex = null;
    filteredIndices = choices.map((_, i) => i);
  }

  function handleOptionSelected(index) {
    const idx = parseInt(index);
    if (isNaN(idx)) return;
    value = choices[idx];
    inputText = choices[idx];
    showOptions = false;
    activeIndex = null;
    filterInput?.blur();
  }

  async function handleKeydown(e) {
    await tick();
    filteredIndices = filterChoices(inputText);
    if (filteredIndices.length > 0 && activeIndex === null) {
      activeIndex = filteredIndices[0];
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (activeIndex === null) {
        activeIndex = filteredIndices[0] ?? null;
      } else {
        const currentPos = filteredIndices.indexOf(activeIndex);
        if (currentPos < filteredIndices.length - 1) {
          activeIndex = filteredIndices[currentPos + 1];
        }
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (activeIndex !== null) {
        const currentPos = filteredIndices.indexOf(activeIndex);
        if (currentPos > 0) {
          activeIndex = filteredIndices[currentPos - 1];
        }
      }
    } else if (e.key === "Enter") {
      if (activeIndex !== null) {
        handleOptionSelected(activeIndex);
      }
    } else if (e.key === "Escape") {
      showOptions = false;
      filterInput?.blur();
    }
  }
</script>

<div class="dropdown-container">
  {#if showLabel}
    <span class="label">{label}</span>
  {/if}
  {#if info}
    <span class="info">{info}</span>
  {/if}
  <div class="wrap" class:focused={showOptions}>
    <div class="wrap-inner">
      <div class="secondary-wrap">
        <input
          role="listbox"
          aria-label={label}
          autocomplete="off"
          bind:value={inputText}
          bind:this={filterInput}
          onkeydown={handleKeydown}
          onblur={handleBlur}
          onfocus={handleFocus}
          readonly={!filterable}
          placeholder={value === null ? "Select..." : ""}
        />
        <div class="icon-wrap">
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5.25 7.5L9 11.25L12.75 7.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
    </div>
  </div>

  {#if showOptions}
    <div class="options-reference">
      <ul
        class="options"
        onmousedown={(e) => {
          e.preventDefault();
          const idx = e.target.closest("li")?.dataset.index;
          if (idx !== undefined) handleOptionSelected(idx);
        }}
        style:top={top}
        style:bottom={bottom}
        style:max-height="{maxHeight}px"
        style:width="{inputWidth}px"
        role="listbox"
      >
        {#each filteredIndices as index}
          <li
            class="item"
            class:selected={index === selectedIndex}
            class:active={index === activeIndex}
            data-index={index}
            role="option"
            aria-selected={index === selectedIndex}
          >
            <span class="check-mark" class:hide={index !== selectedIndex}>✓</span>
            {choices[index]}
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</div>

<style>
  .dropdown-container {
    width: 100%;
    margin-bottom: 4px;
  }
  .label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
    margin-bottom: 6px;
  }
  .info {
    display: block;
    font-size: 12px;
    color: var(--body-text-color-subdued, #9ca3af);
    margin-bottom: 4px;
  }
  .wrap {
    position: relative;
    border-radius: var(--input-radius, 8px);
    background: var(--input-background-fill, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .wrap.focused {
    border-color: var(--input-border-color-focus, #fdba74);
    box-shadow: 0 0 0 2px var(--primary-50, #fff7ed);
  }
  .wrap-inner {
    display: flex;
    position: relative;
    align-items: center;
    padding: 0 10px;
  }
  .secondary-wrap {
    display: flex;
    flex: 1;
    align-items: center;
  }
  input {
    margin: 0;
    outline: none;
    border: none;
    background: inherit;
    width: 100%;
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
    font-family: inherit;
    padding: 7px 0;
  }
  input::placeholder {
    color: var(--input-placeholder-color, #9ca3af);
  }
  input[readonly] {
    cursor: pointer;
  }
  .icon-wrap {
    color: var(--body-text-color-subdued, #9ca3af);
    width: 16px;
    flex-shrink: 0;
    pointer-events: none;
  }
  .options {
    position: fixed;
    z-index: var(--layer-top, 9999);
    margin: 0;
    padding: 4px 0;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    border-radius: var(--input-radius, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, white);
    min-width: fit-content;
    overflow: auto;
    color: var(--body-text-color, #1f2937);
    list-style: none;
  }
  .item {
    display: flex;
    cursor: pointer;
    padding: 6px 10px;
    font-size: 13px;
    word-break: break-word;
  }
  .item:hover,
  .item.active {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .item.selected {
    font-weight: 500;
  }
  .check-mark {
    padding-right: 6px;
    min-width: 16px;
    font-size: 12px;
  }
  .check-mark.hide {
    visibility: hidden;
  }
</style>
