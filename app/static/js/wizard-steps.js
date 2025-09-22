/* wizard.js */

// Script guard to prevent redeclaration errors when script is loaded multiple times
if (typeof window.WizardDragDropManager !== 'undefined') {
  // Class already exists, ensure event listeners are still attached for dynamic content
  console.debug('WizardDragDropManager already loaded, re-initializing for dynamic content');

  // Re-attach functionality for any new content
  if (typeof window.attachSortableLists === 'function') {
    window.attachSortableLists();
  }
  if (typeof window.attachInteractionGating === 'function') {
    window.attachInteractionGating();
  }
  if (typeof window.enhanceEmptyZoneVisibility === 'function') {
    window.enhanceEmptyZoneVisibility();
  }
  if (typeof window.synchronizeAllPhaseHeights === 'function') {
    window.synchronizeAllPhaseHeights();
  }
} else {

/**
 * Utility class for managing wizard step drag-and-drop functionality
 */
class WizardDragDropManager {
  constructor() {
    this.sortableInstances = new Map();
  }

  /**
   * Enhanced configuration for Sortable.js instances
   */
  getSortableConfig(container) {
    return {
      animation: 200,
      handle: '.drag',
      ghostClass: 'opacity-50',
      chosenClass: 'dragging',
      dragClass: 'dragging',
      group: 'wizard-steps',
      fallbackOnBody: true,
      swapThreshold: 0.65,
      onStart: ({ item, from }) => this.handleDragStart(item, from),
      onEnd: ({ to, from, item }) => this.handleDragEnd(to, from, item)
    };
  }

  /**
   * Handle drag start events with enhanced visual feedback
   */
  handleDragStart(item, from) {
    this.highlightCrossPhaseTargets(from, item);
    this.addGlobalDragState();
  }

  /**
   * Handle drag end events with cleanup and API calls
   */
  handleDragEnd(to, from, item) {
    this.clearCrossPhaseHighlights();
    this.removeGlobalDragState();
    this.updateEmptyStates(to, from);
    this.updateStepCounts(to, from);
    this.handleServerUpdate(to, from, item);
  }

  /**
   * Add global drag state for enhanced styling
   */
  addGlobalDragState() {
    document.body.classList.add('dragging-wizard-step');
  }

  /**
   * Remove global drag state
   */
  removeGlobalDragState() {
    document.body.classList.remove('dragging-wizard-step');
  }

  /**
   * Highlight cross-phase drop targets during drag
   */
  highlightCrossPhaseTargets(fromContainer, draggedItem) {
    if (!fromContainer?.dataset.phase || !fromContainer?.dataset.server) return;

    const fromPhase = fromContainer.dataset.phase;
    const serverType = fromContainer.dataset.server;

    const dropZones = document.querySelectorAll(`[data-server="${serverType}"] .drop-zone`);
    dropZones.forEach(zone => {
      const zonePhase = zone.dataset.phase;
      if (zonePhase && zonePhase !== fromPhase) {
        zone.classList.add('cross-phase-target');
      }
    });
  }

  /**
   * Clear cross-phase highlights
   */
  clearCrossPhaseHighlights() {
    const highlightedZones = document.querySelectorAll('.cross-phase-target');
    highlightedZones.forEach(zone => zone.classList.remove('cross-phase-target'));
  }

  /**
   * Update empty state classes for containers
   */
  updateEmptyStates(to, from) {
    [to, from].forEach(container => this.updateEmptyState(container));
  }

  /**
   * Create placeholder HTML for an empty phase
   */
  createPlaceholderHTML(phase) {
    const placeholderText = phase === 'pre' ? 'No pre-invite steps' : 'No post-invite steps';

    return `
      <div class="empty-phase-placeholder absolute inset-0 flex items-center justify-center pointer-events-none">
        <div class="text-center p-12">
          <svg class="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
          <p class="font-medium text-gray-500 dark:text-gray-400">${placeholderText}</p>
          <p class="text-sm text-gray-400 dark:text-gray-500">Drop steps here or create new ones</p>
        </div>
      </div>
    `;
  }

  /**
   * Update empty state of a single wizard step container
   */
  updateEmptyState(container) {
    if (!container?.classList.contains('wizard-steps')) return;

    const hasSteps = container.children.length > 0;
    container.classList.toggle('empty', !hasSteps);

    // Handle placeholder visibility for the drop zone
    const dropZone = container.closest('.drop-zone');
    if (dropZone) {
      let placeholder = dropZone.querySelector('.empty-phase-placeholder');

      if (!hasSteps) {
        // Container is empty - ensure placeholder exists and is visible
        if (!placeholder) {
          // Create placeholder dynamically if it doesn't exist
          const phase = dropZone.dataset.phase;
          if (phase) {
            const placeholderHTML = this.createPlaceholderHTML(phase);
            dropZone.insertAdjacentHTML('beforeend', placeholderHTML);
            placeholder = dropZone.querySelector('.empty-phase-placeholder');
          }
        }
        if (placeholder) {
          placeholder.style.display = 'flex';
        }
      } else {
        // Container has steps - hide or remove placeholder
        if (placeholder) {
          placeholder.style.display = 'none';
        }
      }
    }

    // Synchronize heights between phases after updating empty state
    this.synchronizePhaseHeights(container);
  }

  /**
   * Synchronize heights between pre and post phases to ensure visual balance
   */
  synchronizePhaseHeights(changedContainer) {
    if (!changedContainer?.dataset.server) return;

    const serverType = changedContainer.dataset.server;
    const serverSection = changedContainer.closest('.server-section');
    if (!serverSection) return;

    const preDropZone = serverSection.querySelector('[data-phase="pre"].drop-zone');
    const postDropZone = serverSection.querySelector('[data-phase="post"].drop-zone');

    if (!preDropZone || !postDropZone) return;

    const preWizardSteps = preDropZone.querySelector('.wizard-steps');
    const postWizardSteps = postDropZone.querySelector('.wizard-steps');

    if (!preWizardSteps || !postWizardSteps) return;

    const preHasSteps = !preWizardSteps.classList.contains('empty');
    const postHasSteps = !postWizardSteps.classList.contains('empty');

    // Reset any previously set heights to allow natural measurement
    preDropZone.style.minHeight = '';
    postDropZone.style.minHeight = '';

    // Wait for DOM updates to complete before measuring
    requestAnimationFrame(() => {
      if (preHasSteps && !postHasSteps) {
        // Pre has steps, post is empty - match post height to pre
        const preHeight = preDropZone.offsetHeight;
        postDropZone.style.minHeight = `${preHeight}px`;
      } else if (!preHasSteps && postHasSteps) {
        // Post has steps, pre is empty - match pre height to post
        const postHeight = postDropZone.offsetHeight;
        preDropZone.style.minHeight = `${postHeight}px`;
      }
      // If both have steps or both are empty, let them maintain their natural heights
    });
  }

  /**
   * Synchronize heights for all server sections on page load
   */
  synchronizeAllPhaseHeights() {
    const serverSections = document.querySelectorAll('.server-section');
    serverSections.forEach(serverSection => {
      const preDropZone = serverSection.querySelector('[data-phase="pre"].drop-zone');
      const postDropZone = serverSection.querySelector('[data-phase="post"].drop-zone');

      if (preDropZone && postDropZone) {
        const preWizardSteps = preDropZone.querySelector('.wizard-steps');
        if (preWizardSteps) {
          this.synchronizePhaseHeights(preWizardSteps);
        }
      }
    });
  }

  /**
   * Update step counts in real-time during drag-and-drop
   */
  updateStepCounts(toContainer, fromContainer) {
    if (!toContainer?.dataset.server || !fromContainer?.dataset.server) return;
    if (toContainer.dataset.server !== fromContainer.dataset.server) return;

    const serverType = toContainer.dataset.server;
    this.updatePhaseStepCount(toContainer, serverType);
    if (fromContainer !== toContainer) {
      this.updatePhaseStepCount(fromContainer, serverType);
    }
  }

  /**
   * Update step count for a specific phase
   */
  updatePhaseStepCount(container, serverType) {
    const phase = container.dataset.phase;
    if (!phase) return;

    const stepCount = [...container.children].filter(li =>
      !li.classList.contains('empty-phase-placeholder')
    ).length;

    const countElement = document.getElementById(`${phase}-step-count-${serverType}`);
    if (countElement) {
      countElement.textContent = `${stepCount} steps`;
    }
  }

  /**
   * Handle server-side updates for step reordering and phase changes
   */
  handleServerUpdate(to, from, item) {
    const ids = [...to.children]
      .filter(li => !li.classList.contains('empty-phase-placeholder'))
      .map(li => Number(li.dataset.id));

    if (to.dataset.phase && to.dataset.server) {
      if (from.dataset.phase !== to.dataset.phase) {
        this.updateStepPhase(Number(item.dataset.id), to.dataset.phase, to.dataset.server);
        this.closeEditModal();
      }

      this.reorderSteps(ids, to.dataset.server, to.dataset.phase, to.dataset.reorderUrl);
    }
  }

  /**
   * Update step phase when moving between pre/post
   */
  async updateStepPhase(stepId, newPhase, serverType) {
    try {
      await fetch(`/settings/wizard/${stepId}/update-phase`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phase: newPhase, server_type: serverType })
      });
    } catch (err) {
      console.error('Failed to update step phase:', err);
    }
  }

  /**
   * Reorder steps on the server
   */
  async reorderSteps(ids, serverType, phase, reorderUrl) {
    try {
      await fetch(reorderUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, server_type: serverType, phase })
      });
    } catch (err) {
      console.error('Failed to reorder steps:', err);
    }
  }

  /**
   * Close edit modal to prevent stale phase information
   */
  closeEditModal() {
    const modal = document.getElementById('step-modal');
    if (modal) modal.innerHTML = '';
  }

  /**
   * Enhance empty zone visibility with better styling
   */
  enhanceEmptyZoneVisibility() {
    // CSS now handles the proper styling for empty zones
    // This function is kept for backward compatibility and future enhancements
    const emptyWizardSteps = document.querySelectorAll('.wizard-steps.empty');
    emptyWizardSteps.forEach(container => {
      // Ensure proper setup for Sortable.js on empty containers
      container.style.minHeight = container.style.minHeight || '5rem';
    });
  }
}

// Global instance
const wizardDragDrop = new WizardDragDropManager();

// Make class and functions available globally to enable guard check and re-initialization
window.WizardDragDropManager = WizardDragDropManager;
window.wizardDragDrop = wizardDragDrop;

// Make functions globally available for re-initialization
window.attachSortableLists = attachSortableLists;
window.attachInteractionGating = attachInteractionGating;
window.enhanceEmptyZoneVisibility = enhanceEmptyZoneVisibility;
window.synchronizeAllPhaseHeights = synchronizeAllPhaseHeights;

function attachSortableLists(root = document) {
  root.querySelectorAll('.wizard-steps, .bundle-steps').forEach(container => {
    if (container.dataset.sortableAttached) return;

    // Use enhanced configuration from utility class for wizard steps
    if (container.classList.contains('wizard-steps')) {
      const sortableInstance = new Sortable(container, wizardDragDrop.getSortableConfig(container));
      wizardDragDrop.sortableInstances.set(container, sortableInstance);
    } else {
      // Legacy bundle support
      new Sortable(container, {
        animation: 150,
        handle: '.drag',
        ghostClass: 'opacity-50',
        group: 'wizard-steps',
        onEnd({ to }) {
          const ids = [...to.children].map(li => Number(li.dataset.id));
          fetch(to.dataset.reorderUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ids)
          });
        }
      });
    }

    container.dataset.sortableAttached = '1';
  });
}

// Legacy functions for backward compatibility
const updateStepPhase = (stepId, newPhase, serverType) => wizardDragDrop.updateStepPhase(stepId, newPhase, serverType);
const updateEmptyState = (container) => wizardDragDrop.updateEmptyState(container);
const closeEditModal = () => wizardDragDrop.closeEditModal();
const enhanceEmptyZoneVisibility = () => wizardDragDrop.enhanceEmptyZoneVisibility();
const synchronizeAllPhaseHeights = () => wizardDragDrop.synchronizeAllPhaseHeights();

// Attach Next-button gating that requires an interaction inside step content
function attachInteractionGating(root = document) {
  const next = root.querySelector('#next-btn');
  if (!next) return;
  if (next.dataset.interactionGatingAttached === '1') return;
  next.dataset.interactionGatingAttached = '1';

  // Only activate if the server rendered this step as requiring interaction
  if (next.dataset.disabled === '1') {
    const content = root.querySelector('#wizard-wrapper .prose');

    // 1) Hard-disable HTMX by removing hx-get temporarily
    const savedHxGet = next.getAttribute('hx-get');
    if (savedHxGet != null) {
      next.dataset.savedHxGet = savedHxGet;
      next.removeAttribute('hx-get');
    }

    // 2) Block clicks & keyboard activation at capture phase (before htmx)
    function clickBlocker(e) {
      if (next.dataset.disabled === '1') {
        e.preventDefault();
        e.stopPropagation();
      }
    }
    function keyBlocker(e) {
      if (next.dataset.disabled === '1' && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        e.stopPropagation();
      }
    }
    next.addEventListener('click', clickBlocker, true);  // capture
    next.addEventListener('keydown', keyBlocker, true);  // capture

    function enable() {
      // Restore HTMX capability first
      if (next.dataset.savedHxGet != null) {
        next.setAttribute('hx-get', next.dataset.savedHxGet);
        delete next.dataset.savedHxGet;
      }

      next.dataset.disabled = '0';
      next.removeAttribute('aria-disabled');
      next.removeAttribute('tabindex');
      next.style.pointerEvents = '';
      next.style.opacity = '';
      next.style.cursor = '';

      // Remove tooltip attributes when button is enabled
      next.removeAttribute('data-popover-target');
      next.removeAttribute('data-popover-placement');
      next.removeAttribute('aria-describedby');
      next.removeAttribute('title');

      // Hide the tooltip if it exists
      const tooltipId = next.id + '-tooltip';
      const tooltip = document.getElementById(tooltipId);
      if (tooltip) {
        tooltip.style.display = 'none';
      }

      // Remove blockers & listeners
      next.removeEventListener('click', clickBlocker, true);
      next.removeEventListener('keydown', keyBlocker, true);
      if (content) content.removeEventListener('click', handler, true);
    }

    function handler(ev) {
      const t = ev.target;
      if (!t) return;
      if (t.closest && t.closest('a,button') !== null) enable();
    }

    // Listen for any click within the content that bubbles/captures from links/buttons
    if (content) content.addEventListener('click', handler, true);

    // 3) Apply disabled affordance & interaction lock
    next.setAttribute('tabindex', '-1');
    // Set visual disabled state but keep pointer events for tooltips
    next.style.opacity = '0.6';
    next.style.cursor = 'not-allowed';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  attachSortableLists();
  attachInteractionGating();
  enhanceEmptyZoneVisibility();
  synchronizeAllPhaseHeights();
});
document.body.addEventListener('htmx:load', e => {
  attachSortableLists(e.target);
  attachInteractionGating(e.target);
  enhanceEmptyZoneVisibility();
  synchronizeAllPhaseHeights();
});

} // End of script guard
