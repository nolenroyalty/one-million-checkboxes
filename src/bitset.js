class BitSet {
  constructor({ base64String, count }) {
    const binaryString = atob(base64String);
    this.bytes = new Uint8Array(binaryString.length);
    this.checkCount = count;
    for (let i = 0; i < binaryString.length; i++) {
      this.bytes[i] = binaryString.charCodeAt(i);
    }
  }

  get(index) {
    const byteIndex = Math.floor(index / 8);
    const bitOffset = 7 - (index % 8);
    return (this.bytes[byteIndex] & (1 << bitOffset)) !== 0;
  }

  set(index, value) {
    if (typeof value === "boolean") {
      value = value ? 1 : 0;
    }
    const byteIndex = Math.floor(index / 8);
    const bitOffset = 7 - (index % 8);
    const current = this.bytes[byteIndex] & (1 << bitOffset);
    if (value) {
      this.bytes[byteIndex] |= 1 << bitOffset;
      if (current === 0) {
        this.checkCount++;
      }
    } else {
      this.bytes[byteIndex] &= ~(1 << bitOffset);
      if (current !== 0) {
        this.checkCount--;
      }
    }
  }

  toJSON() {
    return {
      base64String: this._toBase64String(),
      count: this.checkCount,
    };
  }

  static makeEmpty() {
    const bytes = new Uint8Array(125000);
    return new BitSet({
      base64String: BitSet._makeBase64String(bytes),
      count: 0,
    });
  }

  static _makeBase64String(bytes) {
    let binary = "";
    // const bytes = new Uint8Array(this.bytes.buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  _toBase64String() {
    return BitSet._makeBase64String(this.bytes);
  }

  static fromJSON({ base64String, count }) {
    return new BitSet({ base64String, count });
  }

  count() {
    return this.checkCount;
  }

  toggle(index) {
    if (this.get(index)) {
      this.set(index, 0);
    } else {
      this.set(index, 1);
    }
  }
}

export default BitSet;
