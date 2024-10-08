import React, { useState, useCallback, useRef, useEffect } from "react";
import { FixedSizeGrid as Grid } from "react-window";
import { useWindowSize } from "react-use";
import styled, { keyframes } from "styled-components";
import BitSet from "../../bitset";
import INDICES from "../../randomizedColors";
import { abbrNum } from "../../utils";
import useClickTracker from "../../hooks/use-click-tracker";

const TOTAL_CHECKBOXES = 1000000;
const CHECKBOX_SIZE = 35;
const OVERSCAN_COUNT = 5;
const ONE_SECOND_THRESHOLD = 7;
const FIFTEEN_SECOND_THRESHOLD = 80;
const SIXTY_SECOND_THRESHOLD = 240;

const useForceUpdate = ({ bitSetRef, setCheckCount }) => {
  const [, setTick] = useState(0);
  return useCallback(() => {
    setTick((tick) => tick + 1);
    setCheckCount(bitSetRef?.current?.count() || 0);
  }, [bitSetRef, setCheckCount]);
};

const Checkbox = React.memo(
  ({ index, style, isChecked, handleChange, disabled }) => {
    let backgroundColor = null;
    if (INDICES[index]) {
      backgroundColor = `var(--${INDICES[index]}`;
    }

    return (
      <CheckboxWrapper style={style}>
        <StyledCheckbox
          type="checkbox"
          id={`checkbox-${index}`}
          checked={isChecked}
          onChange={handleChange}
          disabled={disabled}
        />
        <MaybeColoredDiv
          style={{ "--background-color": backgroundColor }}
        ></MaybeColoredDiv>
      </CheckboxWrapper>
    );
  }
);

const isDesktopSafari = () => {
  const ua = navigator.userAgent;
  return /^((?!chrome|android).)*safari/i.test(ua) && !/mobile/i.test(ua);
};

const StyledCheckbox = styled.input`
  margin: 0;
  padding: 0;
  width: 25px;
  height: 25px;
  box-shadow: none;
  /* transform: translate(10px, 10px); */

  transform: ${isDesktopSafari() ? "translate(3px, 0px)" : "none"};
`;

const MaybeColoredDiv = styled.div`
  position: absolute;
  pointer-events: none;
  border: 5px solid var(--background-color);
  height: 29px;
  width: 29px;
  border-radius: 2px;
`;

const fadeIn = keyframes`
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
`;

const CheckboxWrapper = styled.div`
  display: flex;
  align-items: center;
  justify-content: center;
  width: ${CHECKBOX_SIZE}px;
  height: ${CHECKBOX_SIZE}px;
  opacity: var(--opacity);
  transition: opacity 0.5s;
  animation: ${fadeIn} 0.4s;
`;

const initialSelfCheckboxState = () => ({
  total: 0,
  totalGold: 0,
  totalRed: 0,
  totalGreen: 0,
  totalPurple: 0,
  totalOrange: 0,
  recentlyChecked: false,
});

const scoreString = ({ selfCheckboxState, allChecked }) => {
  const colors = ["gold", "red", "green", "purple"];
  const colorsToInclude = colors
    .map((color) => {
      const count =
        selfCheckboxState[
          `total${color.charAt(0).toUpperCase()}${color.slice(1)}`
        ];
      if (count !== 0) {
        return [color, count];
      }
      return null;
    })
    .filter((el) => el !== null);

  return (
    <p>
      You {allChecked ? "" : "have "}checked {selfCheckboxState.total}{" "}
      {colorsToInclude.length > 0 ? "(" : ""}
      {colorsToInclude.map(([color, count]) => {
        return (
          <ColorSpan key={color} style={{ "--color": `var(--${color})` }}>
            {abbrNum(count, 2)}
          </ColorSpan>
        );
      })}
      {colorsToInclude.length > 0 ? ") " : " "}
      boxes
    </p>
  );
};

const MailIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
    <polyline points="22,6 12,13 2,6"></polyline>
  </svg>
);

const DollarIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <line x1="12" y1="1" x2="12" y2="23"></line>
    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
  </svg>
);

const App = () => {
  const { width, height } = useWindowSize();
  const gridRef = useRef();
  const [jumpToIndex, setJumpToIndex] = useState("");

  const gridWidth = Math.floor(width * 0.95);
  const columnCount = Math.floor(gridWidth / CHECKBOX_SIZE);
  const rowCount = Math.ceil(TOTAL_CHECKBOXES / columnCount);
  const bitSetRef = useRef(null);
  const frozenBitsetRef = useRef(null);
  const [checkCount, setCheckCount] = React.useState(0);
  const forceUpdate = useForceUpdate({ bitSetRef, setCheckCount });
  const [isLoading, setIsLoading] = useState(true);
  const recentlyCheckedClientSide = useRef({});
  const [clickCounts, trackClick] = useClickTracker();
  const [disabled, setDisabled] = useState(false);
  const [allChecked, setAllChecked] = useState(false);
  const clickTimeout = React.useRef();
  const [singlePlayerMode, setSinglePlayerMode] = useState(false);
  const doAlert = React.useCallback((s) => {
    window.alert(s);
  }, []);

  const [selfCheckboxState, setSelfCheckboxState] = useState(() => {
    const fromLocal = localStorage.getItem("selfCheckboxState");
    try {
      return fromLocal ? JSON.parse(fromLocal) : initialSelfCheckboxState();
    } catch (error) {
      console.error(
        "Failed to parse selfCheckboxState from localStorage:",
        error
      );
      const initial = initialSelfCheckboxState();
      localStorage.setItem("selfCheckboxState", JSON.stringify(initial));
      return initial;
    }
  });

  React.useEffect(() => {
    console.log(JSON.stringify(selfCheckboxState));
    localStorage.setItem(
      "selfCheckboxState",
      JSON.stringify(selfCheckboxState)
    );
  }, [selfCheckboxState]);

  useEffect(() => {
    const fetchInitialState = async () => {
      try {
        const bitset = BitSet.makeFull();
        const frozenBitset = BitSet.makeFull();
        setDisabled(true);
        setAllChecked(true);
        bitSetRef.current = bitset;
        frozenBitsetRef.current = frozenBitset;
        forceUpdate();
        setIsLoading(false);
      } catch (error) {
        console.error("Failed to create initial state:", error);
        setIsLoading(false);
      }
    };

    fetchInitialState();
  }, [forceUpdate]);

  const toggleBit = useCallback(
    async (index) => {
      trackClick();
      if (
        clickCounts.current.oneSecond > ONE_SECOND_THRESHOLD ||
        clickCounts.current.fifteenSeconds > FIFTEEN_SECOND_THRESHOLD ||
        clickCounts.current.sixtySeconds > SIXTY_SECOND_THRESHOLD
      ) {
        doAlert("CHILL LOL");
        setDisabled(true);
        clickTimeout.current && clearTimeout(clickTimeout.current);
        clickTimeout.current = setTimeout(() => {
          setDisabled(false);
        }, 2500);
      } else {
        try {
          bitSetRef.current?.toggle(index);
          const count = bitSetRef.current.count();
          setCheckCount(count);
          if (count >= 1000000) {
            setDisabled(true);
            setAllChecked(true);
          }
          forceUpdate();
          const isChecked = bitSetRef.current?.get(index);
          setSelfCheckboxState((prev) => {
            const newState = { ...prev };
            newState.total += isChecked ? 1 : -1;
            if (INDICES[index]) {
              const color = INDICES[index];
              newState[
                `total${color.charAt(0).toUpperCase()}${color.slice(1)}`
              ] += isChecked ? 1 : -1;
            }
            return newState;
          });
          if (singlePlayerMode) {
            localStorage.setItem(
              "localBitset",
              JSON.stringify(bitSetRef.current)
            );
          } else {
            // socketRef.current?.emit("toggle_bit", { index });
          }
        } catch (error) {
          console.error("Failed to toggle bit:", error);
        } finally {
        }
      }
    },
    [trackClick, clickCounts, doAlert, forceUpdate, singlePlayerMode]
  );

  const Cell = React.useCallback(
    ({ columnIndex, rowIndex, style, isLoading }) => {
      const index = rowIndex * columnCount + columnIndex;
      if (index >= TOTAL_CHECKBOXES) return null;

      let isFrozen = false;
      let isChecked = false;
      if (singlePlayerMode) {
        isChecked = bitSetRef.current?.get(index);
      } else {
        isFrozen = frozenBitsetRef.current.get(index);
        isChecked = isFrozen || bitSetRef.current?.get(index);
      }

      const handleChange = () => {
        toggleBit(index);

        const timeout = setTimeout(() => {
          delete recentlyCheckedClientSide.current[index];
        }, 1000);

        if (recentlyCheckedClientSide.current[index]) {
          clearTimeout(recentlyCheckedClientSide.current[index].timeout);
        }

        recentlyCheckedClientSide.current[index] = {
          value: !isChecked,
          timeout,
        };
      };

      return (
        <Checkbox
          key={index}
          index={index}
          style={style}
          isChecked={isChecked}
          handleChange={handleChange}
          disabled={isFrozen || disabled}
        />
      );
    },
    [columnCount, disabled, toggleBit, singlePlayerMode]
  );

  const handleJumpToCheckbox = (e) => {
    e.preventDefault();
    const index = parseInt(jumpToIndex, 10) - 1; // Subtract 1 because array is 0-indexed
    if (index >= 0 && index < TOTAL_CHECKBOXES) {
      const rowIndex = Math.floor(index / columnCount);
      const columnIndex = index % columnCount;
      gridRef.current.scrollTo({
        scrollTop: rowIndex * CHECKBOX_SIZE,
        scrollLeft: columnIndex * CHECKBOX_SIZE,
      });
    }
    setJumpToIndex("");
  };

  const youHaveChecked = scoreString({ selfCheckboxState, allChecked });
  const cappedCheckCount = Math.min(1000000, checkCount).toLocaleString();

  const enableSinglePlayer = React.useCallback(
    (e) => {
      console.log("enabling single player");
      e.preventDefault();
      setSinglePlayerMode(true);
      const localJson = localStorage.getItem("localBitset");
      setDisabled(false);

      if (localJson) {
        try {
          const parsed = JSON.parse(localJson);
          bitSetRef.current = new BitSet(parsed);
          setCheckCount(bitSetRef.current.count());
          console.log(
            `Loaded single player state, count: ${bitSetRef.current.count()}`
          );
        } catch (error) {
          console.error("Failed to load local bitset:", error);
          const empty = BitSet.makeEmpty();
          bitSetRef.current = empty;
          setCheckCount(0);
          localStorage.setItem("localBitset", JSON.stringify(empty));
          forceUpdate();
        }
        forceUpdate();
      } else {
        const empty = BitSet.makeEmpty();
        bitSetRef.current = empty;
        setCheckCount(0);
        localStorage.setItem("localBitset", JSON.stringify(empty));
        forceUpdate();
      }
    },
    [forceUpdate]
  );

  return (
    <Wrapper>
      <Heading style={{ "--width": columnCount * CHECKBOX_SIZE + "px" }}>
        <SiteHead
          style={{ "--mobile-display": "none", "--desktop-display": "flex" }}
        >
          <span>
            a website by <a href="https://eieio.games">eieio</a>{" "}
          </span>
          <DonoLinks>
            <MailIconLink href="https://eieio.substack.com/">
              {MailIcon()}
            </MailIconLink>
            <DollarIconLink href="https://buymeacoffee.com/eieio">
              {DollarIcon()}
            </DollarIconLink>
          </DonoLinks>
        </SiteHead>
        <Title>One Million Checkboxes</Title>
        <CountHead
          style={{
            "--opacity": isLoading ? 0 : 1,
            "--mobile-display": "none",
            "--desktop-display": "block",
          }}
        >
          {cappedCheckCount} boxes are ✅
        </CountHead>
        <SiteCountMobile>
          <SiteHead
            style={{ "--mobile-display": "flex", "--desktop-display": "none" }}
          >
            <span>
              a website by <a href="https://eieio.games">eieio</a>{" "}
            </span>
            <DonoLinks>
              <MailIconLink href="https://eieio.substack.com/">
                {MailIcon()}
              </MailIconLink>
              <DollarIconLink href="https://buymeacoffee.com/eieio">
                {DollarIcon()}
              </DollarIconLink>
            </DonoLinks>
          </SiteHead>
          <CountHead
            style={{
              "--opacity": isLoading ? 0 : 1,
            }}
          >
            {cappedCheckCount} boxes are ✅
          </CountHead>
        </SiteCountMobile>

        {allChecked ? (
          <Explanation>
            <p>🎉 we checked every box! 🎉</p>
            {singlePlayerMode ? (
              <p>you're playing alone now</p>
            ) : (
              <p>
                but you can still{" "}
                <PlayAlone onClick={enableSinglePlayer}>play alone</PlayAlone>{" "}
                if you'd like
              </p>
            )}
          </Explanation>
        ) : (
          <Explanation>
            <p>checking a box checks it for everyone!</p>
            <p>boxes freeze if they've been checked for a while</p>
          </Explanation>
        )}
        <YouHaveChecked>{youHaveChecked}</YouHaveChecked>
      </Heading>
      <form
        onSubmit={handleJumpToCheckbox}
        style={{
          position: "fixed",
          right: "0",
          bottom: "0",
          zIndex: 1,
          margin: "5px",
        }}
      >
        <JumpInput
          type="number"
          value={jumpToIndex}
          onChange={(e) => setJumpToIndex(e.target.value)}
          placeholder="checkbox number"
          min="1"
          max={TOTAL_CHECKBOXES}
        />
        <JumpButton type="submit">Jump!</JumpButton>
      </form>
      {isLoading ? (
        <p>Loading...</p>
      ) : (
        <Grid
          className="grid"
          width={gridWidth}
          height={height} // Adjust for header and form
          columnCount={columnCount}
          columnWidth={CHECKBOX_SIZE}
          rowCount={rowCount}
          rowHeight={CHECKBOX_SIZE}
          ref={gridRef}
          overscanRowCount={OVERSCAN_COUNT}
          overscanColumnCount={OVERSCAN_COUNT}
          style={{
            width: "fit-content",
            margin: "0 auto",
            "--opacity": isLoading ? 0 : 1,
            transition: "opacity 5.5s",
          }}
        >
          {Cell}
        </Grid>
      )}
    </Wrapper>
  );
};

const Heading = styled.div`
  display: grid;
  justify-content: space-between;

  align-items: baseline;
  width: var(--width);
  margin: -4px auto 0;
  grid-template-columns: 1fr auto 1fr;
  grid-template-rows: auto auto auto;
  grid-template-areas:
    "site title count"
    ". sub ."
    "you you you";

  padding-bottom: 10px;
  border-bottom: 2px solid var(--dark);

  @media (max-width: 850px) {
    grid-template-columns: 1fr auto auto 1fr;
    grid-template-rows: auto auto auto auto;
    grid-template-areas:
      "title title title title"
      ". sub sub ."
      "sitecount sitecount sitecount sitecount"
      "you you you you";
  }
`;

const DonoLinks = styled.span`
  @media (max-width: 550px) {
    margin-top: -6px;
  }
`;

const MailIconLink = styled.a`
  display: inline-flex;
  vertical-align: middle;
  color: var(--blue);
  text-decoration: none;
  border-radius: 5px;
  transition: background-color 0.3s ease;

  &:hover {
    color: var(--dark);
  }
`;

const DollarIconLink = styled.a`
  display: inline-flex;
  vertical-align: middle;
  color: var(--green) !important;
  text-decoration: none;
  border-radius: 5px;
  transition: background-color 0.3s ease;
  margin-left: 2px;

  &:hover {
    color: var(--dark) !important;
  }
`;

const JumpInput = styled.input`
  margin: 0;
  padding: 8px;
  height: 40px;
  font-size: 1rem;
  width: 160px;
  border: 2px solid var(--blue);
  border-radius: 0;
`;

const JumpButton = styled.button`
  margin: 0;
  padding: 8px;
  height: 40px;
  font-size: 1rem;
  background-color: var(--blue);
  border: none;
  color: white;
  cursor: pointer;
  transition: background-color 0.3s;
`;

const Title = styled.h1`
  margin: 0;
  padding: 8px 0 0 0;
  font-size: clamp(1.75rem, 2vw + 1rem, 3.5rem);
  font-family: "Sunset Demi", serif;
  text-align: center;
  grid-area: title;
`;

const SubHead = styled.h2`
  margin: 0;
  padding: 4px 0 0 0;
  flex: 1;
  font-size: clamp(1rem, 0.15vw + 1rem, 2.5rem);
  font-family: "Apercu Regular Pro", sans-serif;

  & a {
    color: var(--blue);
    text-decoration: underline;
    // dotted underline
    text-decoration-style: dashed;
    // move underline a little further down
    text-underline-offset: 0.12em;
    transition: color 0.3s;
  }

  & a:hover {
    color: var(--dark);
  }
`;

const Explanation = styled.p`
  font-size: 1rem;
  text-align: center;
  grid-area: sub;
  font-family: "Apercu Italic Pro", sans-serif;
  // italicize
  font-style: italic;
  margin-top: -10px;
`;

const PlayAlone = styled.button`
  margin: 0;
  padding: 0;
  border: none;
  outline: none;
  display: inline;
  color: var(--blue);
  text-decoration: underline;
  text-decoration-style: dashed;
  // move underline a little further down
  text-underline-offset: 0.12em;
  transition: color 0.3s;
  cursor: pointer;

  &:hover {
    color: var(--dark);
  }
`;

const YouHaveChecked = styled.div`
  font-size: 1rem;
  font-family: "Apercu Bold Pro", sans-serif;
  text-align: right;
  grid-area: you;
  margin-top: 10px;
  display: flex;
  flex-direction: column;
`;

const SiteHead = styled(SubHead)`
  text-align: left;
  grid-area: site;
  /* display: flex; */
  gap: 6px;
  align-items: baseline;

  display: var(--desktop-display);
  @media (max-width: 850px) {
    display: var(--mobile-display);
  }
  @media (max-width: 550px) {
    flex-direction: column;
    gap: 0px;
    width: fit-content;
    flex-grow: 0;
    flex-basis: fit-content;

    /* flex: 0; */
  }
`;

const CountHead = styled(SubHead)`
  text-align: right;
  grid-area: count;
  opacity: var(--opacity);
  transition: opacity 0.5s;
  display: var(--desktop-display);
  @media (max-width: 850px) {
    display: var(--mobile-display);
    flex-grow: 1;
  }
`;

const SiteCountMobile = styled.div`
  grid-area: sitecount;
  display: flex;
  justify-content: space-between;
  display: none;
  @media (max-width: 850px) {
    display: flex;
  }
`;

const Wrapper = styled.div`
  display: flex;
  align-items: center;
  flex-direction: column;
  height: 100dvh;
`;

const ColorSpan = styled.span`
  color: var(--color);

  &:not(:last-of-type):after {
    content: " ";
  }
`;

export default App;
