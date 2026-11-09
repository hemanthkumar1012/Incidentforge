import "@testing-library/jest-dom/vitest";
// jsdom has no <dialog> methods; give them the minimal behaviour the app relies on.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
